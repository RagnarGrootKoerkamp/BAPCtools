import difflib
import itertools
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack, nullcontext
from pathlib import Path
from typing import IO, Optional

from colorama import Fore, Style

from bapctools import (
    config,
    expectations,
    interactive,
    languages,
    parallel,
    problem,
    validate,
)
from bapctools.program import Program
from bapctools.test_case import TestCase
from bapctools.util import (
    BAR_TYPE,
    crop_line,
    crop_output,
    ensure_symlink,
    eprint,
    error,
    ExecResult,
    ExecStatus,
    ProgressBar,
    remove_path,
    shorten_path,
    warn,
)
from bapctools.verdicts import (
    from_string_domjudge,
    RunUntil,
    Verdict,
    Verdicts,
    VerdictTable,
)
from bapctools.visualize import OutputVisualizer


class Run:
    def __init__(
        self, problem: "problem.Problem", submission: "Submission", test_case: TestCase
    ) -> None:
        self.problem = problem
        self.submission = submission
        self.test_case = test_case
        self.name: str = self.test_case.name
        self.result = None

        self.tmpdir: Path = (
            self.problem.tmpdir
            / "runs"
            / self.submission.short_path
            / self.test_case.short_path.with_suffix("")
        )

        self.in_path: Path = self.tmpdir / "testcase.in"
        self.out_path: Path = self.tmpdir / "testcase.out"
        self.feedbackdir: Path = self.in_path.with_suffix(".feedbackdir")

        remove_path(self.tmpdir)
        self.feedbackdir.mkdir(exist_ok=True, parents=True)
        ensure_symlink(self.in_path, self.test_case.in_path)

    # Return an ExecResult object amended with verdict.
    def run(
        self,
        bar: ProgressBar,
        *,
        interaction: bool | Path = False,
    ) -> ExecResult:
        submission_args = self.test_case.get_test_case_yaml(bar).args
        if self.problem.interactive:
            result = interactive.run_interactive_test_case(
                self, bar=bar, interaction=interaction, submission_args=submission_args
            )
            if result is None:
                bar.error(
                    f"No output validator found for test case {self.test_case.name}",
                    resume=True,
                )
                result = ExecResult(
                    None,
                    ExecStatus.REJECTED,
                    0,
                    False,
                    None,
                    None,
                    Verdict.JUDGE_ERROR,
                )
        else:
            assert interaction is not True
            if interaction:
                assert not interaction.is_relative_to(self.tmpdir)
            with interaction.open("a") if interaction else nullcontext(None) as interaction_file:  # type: ignore[attr-defined]
                nextpass = self.feedbackdir / "nextpass.in" if self.problem.multi_pass else None
                max_duration = 0.0
                tle_result = None
                for pass_id in itertools.count(1):
                    result = self.submission.run(
                        self.in_path, self.out_path, args=submission_args or []
                    )
                    max_duration = max(max_duration, result.duration)

                    # write an interaction file for samples
                    if interaction:
                        data = self.in_path.read_text()
                        data = data.removesuffix("\n")
                        data = data.replace("\n", "\n<")
                        print("<", data, sep="", file=interaction_file)

                        data = self.out_path.read_text()
                        data = data.removesuffix("\n")
                        data = data.replace("\n", "\n>")
                        print(">", data, sep="", file=interaction_file)

                    if result.duration > self.problem.limits.time_limit:
                        result.verdict = Verdict.TIME_LIMIT_EXCEEDED
                        if tle_result is None:
                            tle_result = result
                            tle_result.pass_id = pass_id if self.problem.multi_pass else None
                        else:
                            tle_result.timeout_expired |= result.timeout_expired
                        if not self._continue_with_tle(result.verdict, result.timeout_expired):
                            break
                    elif result.status == ExecStatus.ERROR:
                        result.verdict = Verdict.RUNTIME_ERROR
                        msg = f"Exited with code {result.returncode}"
                        if config.args.error and result.err:
                            result.err = f"{msg}:\n{result.err}"
                        else:
                            result.err = msg
                        break

                    result = self._validate_output(bar)
                    if result is None:
                        bar.error(
                            f"No output validator found for test case {self.test_case.name}",
                            resume=True,
                        )
                        result = ExecResult(
                            None,
                            ExecStatus.REJECTED,
                            0,
                            False,
                            None,
                            None,
                            Verdict.JUDGE_ERROR,
                        )
                    elif result.status:
                        result.verdict = Verdict.ACCEPTED
                        validate.sanity_check(
                            self.problem, self.out_path, bar, strict_whitespace=False
                        )
                    elif result.status == ExecStatus.REJECTED:
                        result.verdict = Verdict.WRONG_ANSWER
                        if nextpass and nextpass.is_file():
                            bar.error("got WRONG_ANSWER but found nextpass.in", resume=True)
                            result.verdict = Verdict.JUDGE_ERROR
                    elif result.duration > self.problem.limits.validation_time:
                        bar.error(f"Validator TIMEOUT after {result.duration:.1f}s")
                        result.verdict = Verdict.JUDGE_ERROR
                    else:
                        config.n_error += 1
                        result.verdict = Verdict.JUDGE_ERROR

                    if result.verdict != Verdict.ACCEPTED:
                        break

                    if not self._prepare_nextpass(nextpass):
                        break

                    assert self.problem.limits.validation_passes is not None
                    if pass_id >= self.problem.limits.validation_passes:
                        bar.error("exceeded limit of validation_passes", resume=True)
                        result.verdict = Verdict.JUDGE_ERROR
                        break

                    if interaction:
                        print("---", file=interaction_file)

            assert result is not None
            if self.problem.multi_pass:
                result.pass_id = pass_id

            if tle_result is not None:
                result = tle_result

            result.duration = max_duration

            self._visualize_output(bar)

            # Delete .out files larger than 1GB.
            if (
                not config.args.error
                and self.out_path.is_file()
                and self.out_path.stat().st_size > 1_000_000_000
            ):
                self.out_path.unlink()

        if result.verdict != Verdict.ACCEPTED and (self.feedbackdir / "nextpass.in").is_file():
            assert not self.problem.multi_pass
            bar.warn("Validator created nextpass.in for non multi-pass problem. Ignored.")

        self.result = result
        return result

    # check if we should continue after tle
    def _continue_with_tle(self, verdict: Verdict, timeout_expired: bool) -> bool:
        if not self.problem.multi_pass:
            return False
        if config.args.all == 2 or config.args.reorder:
            return True
        if verdict != Verdict.TIME_LIMIT_EXCEEDED:
            return False
        if timeout_expired:
            return False
        return (
            config.args.verbose > 0
            or config.args.all > 0
            or config.args.action in ["all", "time_limit"]
        )

    # prepare next pass
    def _prepare_nextpass(self, nextpass: Optional[Path]) -> bool:
        if not nextpass or not nextpass.is_file():
            return False
        # clear all files outside of feedbackdir
        for f in self.tmpdir.iterdir():
            if f.resolve() == self.feedbackdir.resolve():
                continue
            remove_path(f)
        # use nextpass.in as next input
        shutil.move(nextpass, self.in_path)
        return True

    def _validate_output(self, bar: ProgressBar) -> Optional[ExecResult]:
        output_validator = self.problem.output_validator()
        if not output_validator:
            return None
        return output_validator.run(
            self.test_case,
            self,
            args=self.test_case.get_test_case_yaml(bar).output_validator_args,
        )

    def _visualize_output(self, bar: BAR_TYPE) -> Optional[ExecResult]:
        if config.args.no_visualizer:
            return None
        output_visualizer = self.problem.visualizer(OutputVisualizer)
        if output_visualizer is None:
            return None
        return output_visualizer.run(
            self.test_case.in_path,
            self.test_case.ans_path.absolute(),
            self.out_path if not self.problem.interactive else None,
            self.feedbackdir,
            args=self.test_case.get_test_case_yaml(bar).output_visualizer_args,
        )


class Submission(Program):
    def __init__(
        self, problem: "problem.Problem", path: Path, skip_double_build_warning: bool = False
    ) -> None:
        super().__init__(
            problem,
            path,
            "submissions",
            limits={
                "code": problem.limits.code,
                "compilation_time": problem.limits.compilation_time,
                "compilation_memory": problem.limits.compilation_memory,
                "memory": problem.limits.memory,
            },
            skip_double_build_warning=skip_double_build_warning,
        )

        self.verdict: Optional[Verdict] = None

        if self.path.absolute().is_relative_to((problem.path / "submissions").absolute()):
            self.expectations: expectations.SubmissionExpectation = (
                problem.expectations().all_matches(self)
            )
        else:
            # External submission are only allowed to get AC
            self.expectations = expectations.SubmissionExpectation(self.name, {"permitted": ["AC"]})

        # parse deprecated @EXPECTED_RESULTS@
        self.expected_results = self._parse_expected_results()
        # NOTE: Judging of interactive problems on systems without `os.wait4` is
        # suboptimal because we cannot determine which of the submission and
        # interactor exits first. This likely makes expectations fail

    # TODO: remove this once domjudge supports the submissions.yaml
    def _parse_expected_results(self) -> Optional[set[Verdict]]:
        permitted = []

        # Look for '@EXPECTED_RESULTS@: ' in all source files. This should be followed by a comma separated list of the following:
        # - ACCEPTED / CORRECT
        # - WRONG_ANSWER / WRONG-ANSWER / NO-OUTPUT
        # - TIME_LIMIT_EXCEEDED / TIMELIMIT
        # - RUN_TIME_ERROR / RUN-ERROR
        # Matching is case insensitive and all source files are checked.
        key = "@EXPECTED_RESULTS@: "
        files = (
            [self.path]
            if self.path.is_file()
            else self.path.glob("**/*")
            if self.path.is_dir()
            else []
        )
        for f in files:
            if not f.is_file():
                continue
            try:
                text = f.read_text().upper()
                beginpos = text.index(key) + len(key)
                endpos = text.find("\n", beginpos)
                arguments = map(str.strip, text[beginpos:endpos].split(","))
                for arg in arguments:
                    try:
                        permitted.append(from_string_domjudge(arg))
                    except ValueError:
                        error(
                            f"@EXPECTED_RESULTS@: `{arg}` for submission {self.short_path} is not valid"
                        )
                        continue
                break
            except (UnicodeDecodeError, ValueError):
                # Skip binary files.
                # Skip files where the key does not occur.
                pass

        if len(permitted) == 0:
            return None
        if len(self.path.parts) >= 3 and self.path.parts[-3] == "submissions":
            # Submissions in any of config.VERDICTS should not have `@EXPECTED_RESULTS@: `, and vice versa.
            # See https://github.com/DOMjudge/domjudge/issues/1861
            subdir = self.short_path.parts[0]
            if subdir in ["accepted", "wrong_answer", "time_limit_exceeded", "run_time_error"]:
                warn(f"@EXPECTED_RESULTS@ in submission {self.short_path} is ignored.")
                return None

        return set(permitted)

    def _get_language_candidates(
        self,
        bar: ProgressBar,
    ) -> list[tuple[languages.Language, list[Path]]]:
        if self.expectations.language is None:
            return super()._get_language_candidates(bar)
        candidates = []
        for lang in languages.languages():
            if lang.code == self.expectations.language:
                score, matching = lang.evaluate(self.input_files)
                if matching:
                    candidates.append((score, lang, matching))
        if not candidates:
            known = {lang.code for lang in languages.languages()}
            closest = difflib.get_close_matches(self.expectations.language, known)
            if not closest:
                msg = ""
            elif len(closest) == 1:
                msg = f", did you mean: {closest[0]}"
            else:
                msg = f", did you mean one of these: {', '.join(closest)}"
            bar.warn(f"Unknown language: {self.expectations.language}{msg}")
        return [(lang, files) for _, lang, files in sorted(candidates, reverse=True)]

    def _set_language(self, language: languages.Language, bar: ProgressBar) -> None:
        restriction = self.problem.settings.languages
        if restriction and language.code not in restriction:
            bar.warn(f"selected language {language.code} is not permitted by the problem.yaml")
        elif language.internal:
            bar.warn(f"selected language {language.code} is not permitted")
        super()._set_language(language, bar)

    def _get_entry_point(self, files: list[Path], bar: ProgressBar) -> tuple[Path, Path, str]:
        if self.expectations.entrypoint is None:
            return super()._get_entry_point(files, bar)
        entrypoint = self.expectations.entrypoint
        file = self.tmpdir / entrypoint
        return (file, file, entrypoint)

    # Run submission on in_path, writing stdout to out_path.
    # args is used by SubmissionInvocation to pass on additional arguments.
    # Returns ExecResult
    # The `generator_timeout` argument is used when a submission is run as a solution when
    # generating test_cases.
    def run(
        self,
        in_path: Path,
        out_path: Path,
        crop: bool = True,
        args: Sequence[str | Path] = [],
        cwd: Optional[Path] = None,
        generator_timeout: bool = False,
    ) -> ExecResult:
        with in_path.open("rb") as in_file, out_path.open("wb") as out_file:
            return self._run(in_file, out_file, crop, args, cwd, generator_timeout)

    def _run(
        self,
        in_file: IO[bytes],
        out_file: IO[bytes],
        crop: bool,
        args: Sequence[str | Path],
        cwd: Optional[Path] = None,
        generator_timeout: bool = False,
        team_error: bool = False,
    ) -> ExecResult:
        assert self.run_command is not None
        # Just for safety reasons, change the cwd.
        if cwd is None:
            cwd = self.tmpdir
        return self._exec_command(
            [*self.run_command, *args],
            crop=crop,
            stdin=in_file,
            stdout=out_file,
            stderr=None if team_error else True,
            cwd=cwd,
            timeout=(
                self.problem.limits.generator_time
                if generator_timeout
                else self.problem.limits.timeout
            ),
        )

    # Run this submission on all test_cases that are given.
    # Returns (OK verdict, printed newline)
    def run_test_cases(
        self,
        max_submission_name_len: int,
        verdict_table: VerdictTable,
        test_cases: Sequence[TestCase],
        skip_test_case: Callable[["Submission", TestCase], bool] = lambda s, t: False,
        *,
        needs_leading_newline: bool,
    ) -> tuple[bool, bool]:
        runs = [Run(self.problem, self, test_case) for test_case in test_cases]
        max_test_case_len = max(len(run.name) for run in runs)
        max_pass_len = 0
        if self.problem.multi_pass:
            max_pass_len = len(str(self.problem.limits.validation_passes))
            max_test_case_len += max_pass_len + len(f":{Fore.CYAN}{Style.RESET_ALL}")
        max_item_len = max_test_case_len + max_submission_name_len - len(self.name)
        padding_len = max_submission_name_len - len(self.name)
        run_until = self.problem.run_until()

        run_test_case: list[TestCase] = []
        skipped_test_case: list[TestCase] = []
        for test_case in test_cases:
            if skip_test_case(self, test_case):
                skipped_test_case.append(test_case)
            else:
                run_test_case.append(test_case)
        verdicts = Verdicts(
            run_test_case,
            self.problem.limits.timeout,
            run_until,
            skipped_test_case,
        )

        verdict_table.next_submission(verdicts)
        bar = verdict_table.ProgressBar(
            self.name,
            count=len(runs),
            max_len=max_item_len,
            needs_leading_newline=needs_leading_newline,
        )

        time_sensitive_lower = self.problem.limits.time_limit / self.problem.limits.ac_to_time_limit
        time_sensitive_upper = (
            self.problem.limits.time_limit * self.problem.limits.time_limit_to_tle
        )

        def process_run(run: Run) -> None:
            if not verdicts.run_is_needed(run.name):
                bar.skip()
                return

            localbar = bar.start(run)
            result = run.run(localbar)
            assert result.verdict is not None

            verdict_table.update_verdicts(run.name, result.verdict, result.duration)

            # Print stderr whenever something is printed
            if result.out and result.err:
                output_type = "PROGRAM STDERR" if self.problem.interactive else "STDOUT"
                data = (
                    "STDERR:"
                    + localbar._format_data(result.err)
                    + f"\n{output_type}:"
                    + localbar._format_data(result.out)
                    + "\n"
                )
            else:
                data = ""
                if result.err:
                    data = crop_output(result.err)
                if result.out:
                    data = crop_output(result.out)

            # Add data from feedbackdir.
            for f in run.feedbackdir.iterdir():
                if f.name.startswith("."):
                    continue  # skip "hidden" files
                if f.name in ["judgemessage.txt", "judgeerror.txt"]:
                    continue
                if f.name.startswith(("judgeimage.", "teamimage.")):
                    data += f"{f.name}: {shorten_path(self.problem, f.parent) / f.name}\n"
                    ensure_symlink(run.problem.path / f.name, f, output=True, relative=False)
                    continue
                if not f.is_file():
                    localbar.warn(f"Validator wrote to {f} but it's not a file.")
                    continue
                try:
                    t = f.read_text()
                except UnicodeDecodeError:
                    localbar.warn(
                        f"Validator wrote to {f} but it cannot be parsed as unicode text."
                    )
                    continue
                if not t:
                    continue
                if data and not data.endswith("\n"):
                    data += "\n"
                data += f"{f.name}:" + localbar._format_data(t) + "\n"

            permitted = self.expectations.all_permitted(run.test_case)
            got_permitted = result.verdict in permitted
            if not got_permitted:
                permittedmsg = f"permitted: [{','.join([v.short() for v in permitted])}]"
                data = "  ".join([permittedmsg, data])

            duration_style = ""
            if (
                result.duration > time_sensitive_lower
                and Verdict.TIME_LIMIT_EXCEEDED not in permitted
            ):
                duration_style = Fore.YELLOW
            if result.verdict == Verdict.ACCEPTED and got_permitted:
                color = f"{Style.DIM}"
            elif got_permitted:
                color = Fore.GREEN
            else:
                color = Fore.RED
                duration_style = ""
            if result.duration >= self.problem.limits.timeout:
                duration_style = f"{Style.BRIGHT}{duration_style}"

            passmsg = (
                f":{Fore.CYAN}{result.pass_id:<{max_pass_len}}{Style.RESET_ALL}"
                if self.problem.multi_pass
                else ""
            )
            test_case = f"{run.name}{Style.RESET_ALL}{passmsg}"
            style_len = len(f"{Style.RESET_ALL}")
            message = f"{color}{result.verdict.short():>3}{duration_style}{result.duration:6.3f}s{Style.RESET_ALL} {Style.DIM}@ {test_case:{max_test_case_len + style_len}}"

            # Update padding since we already print the test case name after the verdict.
            localbar.item_width = padding_len
            localbar.done(got_permitted, message, data, print_item=False)

        parallel.run_tasks(process_run, runs, pin=True)
        bar.item_width -= max_test_case_len + 1

        # We already printed a message if permitted is not satisfied
        passed_permitted = True
        passed_required = True
        for expectation in self.expectations.all_matches():
            passed_cur_required = False
            message = expectation.message
            got = set()
            for run in runs:
                test_case = run.test_case
                if not expectation.matches(test_case):
                    continue
                verdict = verdicts[test_case.name]
                if isinstance(verdict, Verdict):
                    got.add(verdict)
                    passed_permitted &= verdict in expectation.permitted
                    passed_cur_required |= verdict in expectation.required
                    # the spec explicitly says judgemessage, not cerr/cout
                    judgemessage = run.feedbackdir / "judgemessage.txt"
                    if (
                        message is not None
                        and judgemessage.is_file()
                        and message in judgemessage.read_text(errors="replace")
                    ):
                        message = None
                else:
                    # if we do not have verdict we skipped that case
                    # that case could satisfy our constraints => do not warn
                    passed_cur_required = True
                    message = None
            if not passed_cur_required:
                requiredmsg = ",".join([v.short() for v in expectation.required])
                gotmsg = ",".join([v.short() for v in got])
                msg = [f"required: [{requiredmsg}]"]
                if expectation.test_case_glob is not None:
                    msg += ["for", expectation.test_case_glob]
                bar.warn(f"{' '.join(msg)}, got: [{gotmsg}]")
                passed_required = False
            if message is not None:
                bar.warn(f"missing '{crop_line(message, 15)}' in judgemessage.txt")

        verdict = verdicts["."]
        assert isinstance(verdict, Verdict), "Verdict of root must not be empty"
        self.verdict = verdict

        (salient_test_case, salient_duration) = verdicts.salient_test_case()
        salient_print_verdict = self.verdict
        salient_tle = salient_print_verdict == Verdict.TIME_LIMIT_EXCEEDED

        salient_duration_style = ""
        if salient_duration > time_sensitive_lower and not salient_tle:
            salient_duration_style = Fore.YELLOW
        if salient_duration < time_sensitive_upper and salient_tle:
            salient_duration_style = Fore.YELLOW
        if passed_permitted and passed_required:
            color = Fore.GREEN
        else:
            color = Fore.RED
            salient_duration_style = ""
        if salient_duration >= self.problem.limits.timeout:
            salient_duration_style = f"{Style.BRIGHT}{salient_duration_style}"

        # Use a bold summary line if things were printed before
        if bar.logged:
            color = f"{Style.BRIGHT}{color}"
        # Summary line is the only thing shown.
        message = f"{color}{salient_print_verdict.short():>3}{salient_duration_style}{salient_duration:6.3f}s{Style.RESET_ALL} {Style.DIM}@ {salient_test_case:{max_test_case_len}}{Style.RESET_ALL}"

        if verdicts.run_until in [RunUntil.DURATION, RunUntil.ALL]:
            slowest_pair = verdicts.slowest_test_case()
            assert slowest_pair is not None
            (slowest_name, slowest_duration) = slowest_pair
            slowest_verdict = verdicts[slowest_name]
            assert isinstance(slowest_verdict, Verdict), (
                "Verdict of slowest test case must not be empty"
            )
            slowest_test_case = next(t for t in test_cases if t.name == slowest_name)

            slowest_color = Fore.GREEN
            if time_sensitive_lower < slowest_duration < time_sensitive_upper:
                slowest_color = Fore.YELLOW
            if slowest_verdict not in self.expectations.all_permitted(slowest_test_case):
                slowest_color = Fore.RED

            slowest_duration_style = (
                Style.BRIGHT if slowest_duration >= self.problem.limits.timeout else ""
            )

            message += f"  {Style.DIM}{Fore.CYAN}slowest{Fore.RESET}:{Style.RESET_ALL} {slowest_color}{slowest_verdict.short():>3}{slowest_duration_style}{slowest_duration:6.3f}s{Style.RESET_ALL} {Style.DIM}@ {slowest_test_case}{Style.RESET_ALL}"

        printed_newline = bar.finalize(message=message, suppress_newline=True)
        if config.args.tree:
            verdict_table.print(new_lines=0)
            verdict_table.last_printed = []
            eprint()
            printed_newline = True

        return passed_permitted and passed_required, printed_newline

    def test(self) -> None:
        if not self.problem.output_validator():
            return
        test_cases = self.problem.test_cases()
        if not test_cases:
            return

        bar = ProgressBar(self.name, items=test_cases)
        for test_case in test_cases:
            run = Run(self.problem, self, test_case)
            localbar = bar.start(test_case)
            if not self.problem.interactive:
                passmsg = "(pass 1)" if self.problem.multi_pass else ""
                localbar.log(passmsg, color="")

                # we want to directly see the output of the submission
                # => we cannot reuse the interaciton file
                TEE_CODE = R"""
import sys
while True:
    l = sys.stdin.buffer.read1(8096)
    if l==b'': break
    sys.stdout.buffer.write(l)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(l)
"""
                submission_args = test_case.get_test_case_yaml(localbar).args or []
                nextpass = run.feedbackdir / "nextpass.in" if run.problem.multi_pass else None
                for pass_id in itertools.count(1):

                    def run_submission() -> ExecResult:
                        if config.args.verbose:
                            data = run.in_path.read_text().removesuffix("\n")
                            eprint(Fore.YELLOW, data, Style.RESET_ALL, sep="")
                        with ExitStack() as cleanup:
                            out_file = run.out_path.open("wb")
                            cleanup.enter_context(out_file)
                            tee = subprocess.Popen(
                                [sys.executable, "-c", TEE_CODE],
                                stdin=subprocess.PIPE,
                                stdout=None,
                                stderr=out_file,
                            )
                            cleanup.enter_context(tee)
                            assert tee.stdin is not None
                            cleanup.callback(tee.stdin.close)

                            in_file = run.in_path.open("rb")
                            cleanup.enter_context(in_file)
                            result = self._run(
                                in_file, tee.stdin, False, submission_args, team_error=True
                            )
                            tee.stdin.close()
                            tee.wait()

                        assert result.err is None
                        assert result.status != ExecStatus.REJECTED
                        if result.duration >= self.problem.limits.time_limit:
                            result.verdict = Verdict.TIME_LIMIT_EXCEEDED
                        elif result.status == ExecStatus.ERROR:
                            result.verdict = Verdict.RUNTIME_ERROR
                            msg = f"Exited with code {result.returncode}"
                            if config.args.error and result.err:
                                result.err = f"{msg}:\n{result.err}"
                            else:
                                result.err = msg
                        return result

                    result = run_submission()
                    if result.verdict is None:
                        val_result = run._validate_output(localbar)
                        if val_result is not None and config.args.error:
                            result.err = val_result.err
                        if val_result is None:
                            result.verdict = Verdict.JUDGE_ERROR
                            result.err = f"No output validator found for test case {test_case.name}"
                        elif val_result.status:
                            result.verdict = Verdict.ACCEPTED
                        elif val_result.status == ExecStatus.REJECTED:
                            result.verdict = Verdict.WRONG_ANSWER
                        elif result.duration > self.problem.limits.validation_time:
                            result.verdict = Verdict.JUDGE_ERROR
                            result.err = f"Validator TIMEOUT after {result.duration:.1f}s"
                        else:
                            config.n_error += 1
                            result.verdict = Verdict.JUDGE_ERROR
                            result.err = val_result.err

                    if result.err:
                        eprint(Fore.YELLOW, result.err.removesuffix("\n"), Style.RESET_ALL, sep="")

                    if result.verdict != Verdict.ACCEPTED:
                        config.n_error += 1
                        msg = f"{Fore.RED}{result.verdict}{Style.RESET_ALL}"
                    else:
                        msg = f"{Fore.GREEN}{result.verdict}{Style.RESET_ALL}"
                    eprint(f"{msg} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}\n")

                    if result.verdict != Verdict.ACCEPTED:
                        break

                    if not run._prepare_nextpass(nextpass):
                        break
                    passmsg = f" (pass {pass_id + 1})" if self.problem.multi_pass else ""
                    eprint(ProgressBar.action(f"Running {self.name}", test_case.name + passmsg))
            else:
                # Interactive problem.
                localbar.log("(logging interaction)", color="")
                optional_result = interactive.run_interactive_test_case(
                    run, bar=localbar, interaction=True, validator_error=True, team_error=True
                )
                if optional_result is None:
                    config.n_error += 1
                    eprint(
                        f"{Fore.RED}No output validator found for test case {test_case.name}{Style.RESET_ALL}"
                    )
                    continue
                result = optional_result
                if config.args.error and result.err:
                    eprint(Fore.YELLOW, result.err.removesuffix("\n"), Style.RESET_ALL, sep="")
                if result.verdict != Verdict.ACCEPTED:
                    config.n_error += 1
                    msg = f"{Fore.RED}{result.verdict}{Style.RESET_ALL}"
                else:
                    msg = f"{Fore.GREEN}{result.verdict}{Style.RESET_ALL}"
                eprint(f"{msg} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}")
            localbar.done()
        bar.finalize(suppress_newline=True)

    # Run the submission using stdin as input.
    def test_interactive(self) -> None:
        if not self.problem.output_validator():
            return

        bar = ProgressBar("Running " + str(self.name), max_len=1, count=1)
        bar.start()

        is_tty = sys.stdin.isatty()

        for tc in itertools.count(1):
            name = f"Run {tc}"
            bar.update(1, len(name))
            localbar = bar.start(name)
            # Reinitialize the underlying program, so that changes to the source
            # code can be picked up in build.
            super().__init__(
                self.problem,
                self.path,
                self.subdir,
                limits=self.limits,
                skip_double_build_warning=True,
            )
            localbar.log("from stdin" if is_tty else "from file")

            TEE_CODE = R"""
import sys
while True:
    l = sys.stdin.buffer.read1(8096)
    if l=='': break
    sys.stdout.buffer.write(l)
    sys.stdout.buffer.flush()
"""
            closed = []

            def close(fd: int) -> None:
                if fd not in closed:
                    closed.append(fd)
                    os.close(fd)

            with ExitStack() as cleanup:
                # Launch a separate thread to pass stdin to a pipe.
                r, w = os.pipe()
                cleanup.callback(close, r)
                cleanup.callback(close, w)

                # Wait for first input (and ensure that the read is not partially buffered in python)
                read = os.read(sys.stdin.fileno(), 1)
                if not read:
                    return
                if not self.build(localbar):
                    return
                os.write(w, read)

                writer = subprocess.Popen([sys.executable, "-c", TEE_CODE], stdin=None, stdout=w)
                cleanup.enter_context(writer)
                cleanup.callback(writer.kill)

                close(w)

                assert self.run_command is not None
                result = self._exec_command(
                    self.run_command,
                    crop=False,
                    stdin=r,
                    stdout=None,
                    stderr=None,
                    timeout=None,  # no timeout since we wait for user input
                )
                assert result.err is None and result.out is None

            if not result.status:
                config.n_error += 1
                status = None
                eprint(
                    f"{Fore.RED}Run time error!{Style.RESET_ALL} exit code {result.returncode} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}"
                )
            else:
                status = f"{Fore.GREEN}Done:"

            if status:
                eprint(
                    f"{status}{Style.RESET_ALL} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}"
                )
            eprint()

            localbar.done()

            if not is_tty:
                break
