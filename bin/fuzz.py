import config
import run
import random
import generate
import time
import threading
from colorama import Fore, Style

import parallel
from util import *
from testcase import Testcase
from validate import OutputValidator, Mode
from verdicts import Verdict

# STEPS:
# 1. Find generator invocations depending on {seed}.
# 2. Generate a testcase + .ans using the rule using a random seed.
# 3. Run all submissions against the generated testcase.
# 4. When at least one submissions fails: create a generated testcase:
#      data/fuzz/1.in: <generator rule with hardcoded seed>
#    by using a numbered directory data/fuzz.


class GeneratorTask:
    def __init__(self, fuzz, t, i, tmp_id):
        self.fuzz = fuzz
        self.generator = t.generator
        self.solution = t.config.solution
        self.i = i
        self.tmp_id = tmp_id

        # Pick a random seed.
        assert self.generator.program is not None
        self.seed = random.randrange(0, 2**31)
        self.command = self.generator.cache_command(seed=self.seed)

        self.save_mutex = threading.Lock()
        self.saved = False

    def run(self, bar):
        if self._run(bar):
            self.fuzz.finish_task(self.tmp_id)
        else:
            self.fuzz.finish_task(self.tmp_id, 1 + len(self.fuzz.submissions))

    def _run(self, bar):
        # GENERATE THE TEST DATA
        dir = Path('fuzz') / f'tmp_id_{str(self.tmp_id)}'
        cwd = self.fuzz.problem.tmpdir / 'tool_runs' / dir
        cwd.mkdir(parents=True, exist_ok=True)
        name = 'testcase'
        infile = cwd / (name + '.in')
        ansfile = cwd / (name + '.ans')

        localbar = bar.start(f'{self.i}: {self.command}')
        localbar.log()
        localbar.done()

        localbar = bar.start(f'{self.i}: generate')
        result = self.generator.run(localbar, cwd, name, self.seed)
        if not result.status:
            return False  # No need to call bar.done() in this case, because the Generator calls bar.error()
        localbar.done()

        testcase = Testcase(self.fuzz.problem, infile, short_path=dir / (name + '.in'))

        # Validate the generated .in.
        localbar = bar.start(f'{self.i}: validate input')
        if not testcase.validate_format(Mode.INPUT, bar=localbar, constraints=None):
            localbar.done(False)
            return False
        localbar.done()

        # Generate .ans.
        if not self.fuzz.problem.interactive and not self.fuzz.problem.multipass:
            if self.solution and not testcase.ans_path.is_file():
                if testcase.ans_path.is_file():
                    testcase.ans_path.unlink()
                # Run the solution and validate the generated .ans.
                localbar = bar.start(f'{self.i}: generate ans')
                if not self.solution.run(bar, cwd).status:
                    localbar.done()
                    return False
                localbar.done()

            if ansfile.is_file():
                localbar = bar.start(f'{self.i}: validate output')
                if not testcase.validate_format(Mode.ANSWER, bar=localbar):
                    localbar.done(False)
                    return False
                localbar.done()
            else:
                bar.error(f'{self.i}: {ansfile.name} was not generated.')
                return False
        else:
            if not testcase.ans_path.is_file():
                testcase.ans_path.write_text('')

        # Run all submissions against the testcase.
        with self.fuzz.queue:
            for submission in self.fuzz.submissions:
                self.fuzz.queue.put(SubmissionTask(self, submission, testcase, self.tmp_id))
        return True

    def save_test(self, bar):
        if self.saved:
            return
        save = False
        # emulate atomic swap of save and self.saved
        with self.save_mutex:
            if not self.saved:
                self.saved = True
                save = True
        # only save rule if we set self.saved to True
        if save:
            localbar = bar.start(f'{self.i}: {self.command}')
            localbar.log('Saving testcase in generators.yaml.')
            localbar.done()
            self.fuzz.save_test(self.command)


class SubmissionTask:
    def __init__(self, generator_task, submission, testcase, tmp_id):
        self.generator_task = generator_task
        self.submission = submission
        self.testcase = testcase
        self.tmp_id = tmp_id

    def run(self, bar):
        self._run(bar)
        self.generator_task.fuzz.finish_task(self.tmp_id)

    def _run(self, bar):
        r = run.Run(self.generator_task.fuzz.problem, self.submission, self.testcase)
        localbar = bar.start(f'{self.generator_task.i}: {self.submission.name}')
        result = r.run(localbar)
        if result.verdict != Verdict.ACCEPTED:
            self.generator_task.save_test(bar)
            localbar.done(False, f'{result.verdict}!')
        else:
            localbar.done()


class Fuzz:
    def __init__(self, problem):
        self.generators_yaml_mutex = threading.Lock()
        self.problem = problem

        # GENERATOR INVOCATIONS
        generator_config = generate.GeneratorConfig(self.problem, config.args.testcases)
        self.testcase_rules = []

        # Filter to only keep valid rules depending on seed without duplicates from count
        added_testcase_rules = set()

        def add_testcase(t):
            if (
                t.in_is_generated
                and t.parse_error is None
                and t.generator.uses_seed
                and t.generator.command_string.strip() not in added_testcase_rules
            ):
                self.testcase_rules.append(t)
                added_testcase_rules.add(t.generator.command_string.strip())

        generator_config.root_dir.walk(add_testcase, dir_f=None)
        if len(self.testcase_rules) == 0:
            return

        generator_config.build(build_visualizers=False)

        # BUILD VALIDATORS
        self.problem.validators(OutputValidator)

        # SUBMISSIONS
        self.submissions = self.problem.submissions(accepted_only=True)

    def run(self):
        if not has_ryaml:
            error('Fuzzing needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.')
            return False

        if len(self.testcase_rules) == 0:
            error('No invocations depending on {seed} found.')
            return False

        if len(self.submissions) == 0:
            error('No submissions found.')
            return False

        message('Press CTRL+C to stop\n', 'Fuzz', color_type=MessageType.LOG)

        # config.args.no_bar = True
        # max(len(s.name) for s in self.submissions)
        bar = ProgressBar(f'Fuzz', max_len=60)
        self.start_time = time.monotonic()
        self.iteration = 0
        self.tasks = 0
        self.queue = parallel.new_queue(lambda task: task.run(bar), pin=True)

        def soft_exit(sig, frame):
            if self.queue.aborted:
                fatal('Running interrupted', force=True)
            else:
                self.queue.abort()
                with bar:
                    bar.clearline()
                    message(
                        'Running interrupted (waiting on remaining tasks)\n',
                        '\nFuzz',
                        color_type=MessageType.ERROR,
                    )

        signal.signal(signal.SIGINT, soft_exit)

        # pool of ids used for generators
        self.tmp_ids = 2 * max(1, self.queue.num_threads) + 1
        self.free_tmp_id = {*range(self.tmp_ids)}
        self.tmp_id_count = [0] * self.tmp_ids

        # add first generator task
        self.finish_task()

        # wait for the queue to run empty (after config.args.time)
        self.queue.join()
        # At this point, no new tasks may be started anymore.
        self.queue.done()

        if self.queue.aborted:
            fatal('Running interrupted', force=True)

        bar.done()
        bar.finalize()
        return True

    # finish task from generator with tmp_id
    # also add new tasks if queue becomes too empty
    def finish_task(self, tmp_id=None, count=1):
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
                tmp_id = min(self.free_tmp_id)
                self.free_tmp_id.remove(tmp_id)
                self.tmp_id_count[tmp_id] = new_tasks
                self.tasks += new_tasks
                self.queue.put(
                    GeneratorTask(self, testcase_rule, self.iteration, tmp_id), priority=1
                )

    # Write new rule to yaml
    # lock between read and write to ensure that no rule gets lost
    def save_test(self, command):
        with self.generators_yaml_mutex:
            generators_yaml = self.problem.path / 'generators/generators.yaml'
            data = None
            if generators_yaml.is_file():
                data = read_yaml(generators_yaml)
            if data is None:
                data = ruamel.yaml.comments.CommentedMap()

            def get_or_add(yaml, key, t=ruamel.yaml.comments.CommentedMap):
                assert isinstance(data, ruamel.yaml.comments.CommentedMap)
                if not key in yaml or yaml[key] is None:
                    yaml[key] = t()
                assert isinstance(yaml[key], t)
                return yaml[key]

            parent = get_or_add(data, 'data')
            parent = get_or_add(parent, 'fuzz')
            entry = get_or_add(parent, 'data', ruamel.yaml.comments.CommentedSeq)

            entry.append(ruamel.yaml.comments.CommentedMap())
            entry[-1][''] = command

            # Overwrite generators.yaml.
            write_yaml(data, generators_yaml)
