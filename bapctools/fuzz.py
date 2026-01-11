import random
import shutil
import signal
import threading
import time
from pathlib import Path
from typing import Any, Optional

from colorama import Style
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from bapctools import config, generate, parallel, problem
from bapctools.run import Run, Submission
from bapctools.testcase import Testcase
from bapctools.util import (
    eprint,
    error,
    fatal,
    PrintBar,
    ProgressBar,
    read_yaml,
    ryaml_get_or_add,
    write_yaml,
)
from bapctools.validate import Mode, OutputValidator
from bapctools.verdicts import Verdict

# STEPS:
# 1. Find generator invocations depending on {seed}.
# 2. Generate a testcase + .ans using the rule using a random seed.
# 3. Run all submissions against the generated testcase.
# 4. When at least one submissions fails: create a generated testcase:
#      data/fuzz/1.in: <generator rule with hardcoded seed>
#    by using a numbered directory data/fuzz.


class GeneratorTask:
    def __init__(self, fuzz: "Fuzz", t: generate.TestcaseRule, i: int, tmp_id: int) -> None:
        self.fuzz = fuzz
        self.rule = t
        generator = t.generator
        assert generator is not None
        self.generator = generator
        self.solution = t.config.solution
        self.i = i
        self.tmp_id = tmp_id

        # Pick a random seed.
        assert self.generator.program is not None
        self.seed = random.randrange(0, 2**31)
        self.command = self.generator.cache_command(seed=self.seed)

        self.save_mutex = threading.Lock()
        self.saved = False

    def run(self, bar: ProgressBar) -> None:
        if self._run(bar):
            self.fuzz.finish_task(self.tmp_id)
        else:
            self.fuzz.finish_task(self.tmp_id, 1 + len(self.fuzz.submissions))

    def _run(self, bar: ProgressBar) -> bool:
        # GENERATE THE TEST DATA
        dir = Path("fuzz") / f"tmp_id_{str(self.tmp_id)}"
        cwd = self.fuzz.problem.tmpdir / "tool_runs" / dir
        shutil.rmtree(cwd, ignore_errors=True)
        cwd.mkdir(parents=True, exist_ok=True)
        name = "testcase"
        infile = cwd / (name + ".in")
        ansfile = cwd / (name + ".ans")

        # The extra newline at the end is to ensure this line stays visible.
        localbar = bar.start(f"{self.i}: {self.command}\n")
        localbar.done()

        localbar = bar.start(f"{self.i}: generate")
        result = self.generator.run(localbar, cwd, name, self.seed)
        self.fuzz.queue.ensure_alive()
        if not result.status:
            return False  # No need to call bar.done() in this case, because the Generator calls bar.error()
        if ".ans" in self.rule.hardcoded:
            ansfile.write_text(self.rule.hardcoded[".ans"])
        localbar.done()

        testcase = Testcase(self.fuzz.problem, infile, short_path=dir / (name + ".in"))

        # Validate the generated .in.
        localbar = bar.start(f"{self.i}: validate input")
        if not testcase.validate_format(Mode.INPUT, bar=localbar, constraints=None):
            self.fuzz.queue.ensure_alive()
            localbar.done(False)
            return False
        self.fuzz.queue.ensure_alive()
        localbar.done()

        # Generate .ans.
        if not ansfile.is_file():
            if self.fuzz.problem.settings.ans_is_output:
                if self.solution:
                    # Run the solution and validate the generated .ans.
                    localbar = bar.start(f"{self.i}: generate ans")
                    if not self.solution.run(bar, cwd).status:
                        self.fuzz.queue.ensure_alive()
                        localbar.done()
                        return False
                    self.fuzz.queue.ensure_alive()
                    localbar.done()
            elif self.fuzz.problem.interactive or self.fuzz.problem.multi_pass:
                ansfile.write_text("")

        if ansfile.is_file():
            localbar = bar.start(f"{self.i}: validate output")
            if not testcase.validate_format(Mode.ANSWER, bar=localbar):
                self.fuzz.queue.ensure_alive()
                localbar.done(False)
                return False
            self.fuzz.queue.ensure_alive()
            localbar.done()
        else:
            bar.error(f"{self.i}: {ansfile.name} was not generated.")
            return False

        # Run all submissions against the testcase.
        with self.fuzz.queue:
            for submission in self.fuzz.submissions:
                self.fuzz.queue.put(SubmissionTask(self, submission, testcase, self.tmp_id))
        return True

    def get_command(self) -> dict[str, str] | str:
        if not self.fuzz.problem.settings.ans_is_output and ".ans" in self.rule.hardcoded:
            return {"generate": self.command, "ans": self.rule.hardcoded[".ans"]}
        else:
            return self.command

    def save_test(self, bar: ProgressBar, submission: Submission, verdict: Verdict) -> None:
        if self.saved:
            return
        save = False
        # emulate atomic swap of save and self.saved
        with self.save_mutex:
            if not self.saved:
                self.saved = True
                save = True
        self.fuzz.queue.ensure_alive()
        # only save rule if we set self.saved to True
        if save:
            localbar = bar.start(f"{self.i}: {self.command}")
            localbar.log("Saving testcase in generators.yaml.")
            self.fuzz.save_test(self.get_command(), submission, verdict)
            self.fuzz.queue.ensure_alive()
            localbar.done()


class SubmissionTask:
    def __init__(
        self,
        generator_task: GeneratorTask,
        submission: Submission,
        testcase: Testcase,
        tmp_id: int,
    ) -> None:
        self.generator_task = generator_task
        self.submission = submission
        self.testcase = testcase
        self.tmp_id = tmp_id

    def run(self, bar: ProgressBar) -> None:
        self._run(bar)
        self.generator_task.fuzz.finish_task(self.tmp_id)

    def _run(self, bar: ProgressBar) -> None:
        r = Run(self.generator_task.fuzz.problem, self.submission, self.testcase)
        localbar = bar.start(f"{self.generator_task.i}: {self.submission.name}")
        result = r.run(localbar)
        assert result.verdict is not None
        self.generator_task.fuzz.queue.ensure_alive()
        if result.verdict != Verdict.ACCEPTED:
            self.generator_task.save_test(bar, self.submission, result.verdict)
            localbar.done(False, f"{result.verdict}!")
        else:
            localbar.done()


class FuzzProgressBar(ProgressBar):
    def __init__(
        self,
        queue: parallel.AbstractQueue[GeneratorTask | SubmissionTask],
        prefix: str,
        max_len: int,
    ) -> None:
        super().__init__(prefix, max_len)
        self.queue = queue

    def _print(self, *args: Any, **kwargs: Any) -> None:
        self.queue.ensure_alive()
        super()._print(*args, **kwargs)


class Fuzz:
    def __init__(self, problem: problem.Problem) -> None:
        self.generators_yaml_mutex = threading.Lock()
        self.problem = problem
        self.summary: dict[Submission, set[Verdict]] = {}
        self.added = 0

        # GENERATOR INVOCATIONS
        generator_config = generate.GeneratorConfig(self.problem, config.args.testcases)
        self.testcase_rules: list[generate.TestcaseRule] = []

        # Filter to deduplicaterules
        added_testcase_rule_data = set()

        def add_testcase(t: generate.TestcaseRule) -> None:
            if (
                not t.in_is_generated
                or t.root in config.INVALID_CASE_DIRECTORIES
                or t.parse_error is not None
                or t.generator is None
                or not t.generator.uses_seed
            ):
                return

            testcase_rule_data = [t.generator.command_string.strip()]
            if not problem.settings.ans_is_output and ".ans" in t.hardcoded:
                testcase_rule_data.append(t.hardcoded[".ans"])
            testcase_rule_key = tuple(testcase_rule_data)

            if testcase_rule_key in added_testcase_rule_data:
                return

            self.testcase_rules.append(t)
            added_testcase_rule_data.add(testcase_rule_key)

        generator_config.root_dir.walk(add_testcase, dir_f=None)
        if len(self.testcase_rules) == 0:
            return

        generator_config.build(build_visualizers=False)

        # BUILD VALIDATORS
        self.problem.validators(OutputValidator)

        # SUBMISSIONS
        self.submissions = self.problem.selected_or_accepted_submissions()

    def run(self) -> bool:
        if len(self.testcase_rules) == 0:
            error("No invocations depending on {seed} found.")
            return False

        if not self.submissions:
            error("No submissions found.")
            return False

        def runner(task: GeneratorTask | SubmissionTask) -> None:
            task.run(bar)

        self.start_time = time.monotonic()
        self.iteration = 0
        self.tasks = 0
        self.queue = parallel.new_queue(runner, pin=True)

        # pool of ids used for generators
        self.tmp_ids = 2 * max(1, self.queue.num_threads) + 1
        self.free_tmp_id = {*range(self.tmp_ids)}
        self.tmp_id_count = [0] * self.tmp_ids

        max_len = max(
            25,
            *[len(s.name) for s in self.submissions],
            *[
                len(t.generator.cache_command(seed=2**32))
                for t in self.testcase_rules
                if t.generator is not None
            ],
        )
        max_len += len(f"{self.tmp_ids}: ")
        # we use a PrintBar after an abort
        printbar = PrintBar("Fuzz", max_len=max_len)
        printbar.log("Press CTRL+C to stop\n")
        bar = FuzzProgressBar(self.queue, "Fuzz", max_len=max_len)

        def soft_exit(sig: Any, frame: Any) -> None:
            if self.queue.aborted:
                fatal("Running interrupted", force=True)
            else:
                self.queue.abort()
                with bar:
                    eprint(bar.carriage_return)
                    printbar.error("Running interrupted (waiting on remaining tasks)\n")

        old_handler = signal.signal(signal.SIGINT, soft_exit)

        # add first generator task
        self.finish_task()

        # wait for the queue to run empty (after config.args.time)
        self.queue.join()
        # At this point, no new tasks may be started anymore.
        self.queue.done()

        signal.signal(signal.SIGINT, old_handler)

        for submission, verdicts in self.summary.items():
            msg = ", ".join(f"{v.color()}{v.short()}{Style.RESET_ALL}" for v in sorted(verdicts))
            printbar.start(submission).log(msg, color="")
        printbar.log(f"Found {self.added} testcases in total.", color="")

        if self.queue.aborted:
            fatal("Running interrupted")

        bar.done()
        bar.finalize()

        return True

    # finish task from generator with tmp_id
    # also add new tasks if queue becomes too empty
    def finish_task(self, tmp_id: Optional[int] = None, count: int = 1) -> None:
        with self.queue:
            # return tmp_id (and reuse it if all submissions are finished)
            if tmp_id is not None:
                self.tasks -= count
                self.tmp_id_count[tmp_id] -= count
                if self.tmp_id_count[tmp_id] == 0:
                    self.free_tmp_id.add(tmp_id)

            # add new generator runs to fill up queue
            while self.tasks < self.tmp_ids:
                # don't add new tasks after time is up
                if time.monotonic() - self.start_time > config.args.time:
                    return

                testcase_rule = self.testcase_rules[self.iteration % len(self.testcase_rules)]
                self.iteration += 1
                # 1 new generator tasks which will also create one task per submission
                new_tasks = 1 + len(self.submissions)
                new_tmp_id = min(self.free_tmp_id)
                self.free_tmp_id.remove(new_tmp_id)
                self.tmp_id_count[new_tmp_id] = new_tasks
                self.tasks += new_tasks
                self.queue.put(
                    GeneratorTask(self, testcase_rule, self.iteration, new_tmp_id),
                    priority=1,
                )

    # Write new rule to yaml
    # lock between read and write to ensure that no rule gets lost
    def save_test(
        self, command: dict[str, str] | str, submission: Submission, verdict: Verdict
    ) -> None:
        with self.generators_yaml_mutex:
            generators_yaml = self.problem.path / "generators/generators.yaml"
            data = None
            if generators_yaml.is_file():
                raw_data = read_yaml(generators_yaml)
                assert isinstance(raw_data, CommentedMap)
                data = raw_data
            if data is None:
                data = CommentedMap()

            parent = ryaml_get_or_add(data, "data")
            parent = ryaml_get_or_add(parent, "fuzz")
            entry = ryaml_get_or_add(parent, "data", CommentedSeq)

            entry.append(CommentedMap())
            entry[-1][""] = command

            # Overwrite generators.yaml.
            write_yaml(data, generators_yaml)

            self.summary.setdefault(submission, set()).add(verdict)
            self.added += 1
