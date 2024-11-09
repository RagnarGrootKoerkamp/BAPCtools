import os
import shutil
import subprocess
import sys

from colorama import Fore, Style

import config
import interactive
import parallel
import problem
import program
import validate
from util import (
    crop_output,
    ensure_symlink,
    error,
    ExecResult,
    ExecStatus,
    exec_command,
    is_bsd,
    is_windows,
    ProgressBar,
    warn,
)
from verdicts import from_string, from_string_domjudge, RunUntil, Verdict, Verdicts


class Run:
    def __init__(self, problem: "problem.Problem", submission, testcase):
        self.problem = problem
        self.submission = submission
        self.testcase = testcase
        self.name = self.testcase.name
        self.result = None

        self.tmpdir = (
            self.problem.tmpdir
            / 'runs'
            / self.submission.short_path
            / self.testcase.short_path.with_suffix('')
        )

        self.in_path = self.tmpdir / 'testcase.in'
        self.out_path = self.tmpdir / 'testcase.out'
        self.feedbackdir = self.in_path.with_suffix('.feedbackdir')

        if self.tmpdir.is_file():
            self.tmpdir.unlink()
        elif self.tmpdir.exists():
            shutil.rmtree(self.tmpdir)

        self.feedbackdir.mkdir(exist_ok=True, parents=True)
        ensure_symlink(self.in_path, self.testcase.in_path)

    # Return an ExecResult object amended with verdict.
    def run(self, bar, *, interaction=None, submission_args=None):
        if self.problem.interactive:
            result = interactive.run_interactive_testcase(
                self, interaction=interaction, submission_args=submission_args
            )
        else:
            if interaction:
                assert not interaction.is_relative_to(self.tmpdir)
                interaction = interaction.open('a')
            nextpass = self.feedbackdir / 'nextpass.in' if self.problem.multipass else False
            pass_id = 0
            max_duration = 0
            tle_result = None
            while True:
                pass_id += 1
                result = self.submission.run(self.in_path, self.out_path)
                max_duration = max(max_duration, result.duration)

                # write an interaction file for samples
                if interaction:
                    data = self.in_path.read_text()
                    if len(data) > 0 and data[-1] == '\n':
                        data = data[:-1]
                    data = data.replace('\n', '\n<')
                    print('<', data, sep='', file=interaction)

                    data = self.out_path.read_text()
                    if len(data) > 0 and data[-1] == '\n':
                        data = data[:-1]
                    data = data.replace('\n', '\n>')
                    print('>', data, sep='', file=interaction)

                if result.duration > self.problem.settings.timelimit:
                    result.verdict = Verdict.TIME_LIMIT_EXCEEDED
                    if tle_result is None:
                        tle_result = result
                        tle_result.pass_id = pass_id if self.problem.multipass else None
                    else:
                        tle_result.timeout_expired |= result.timeout_expired
                    if not self._continue_with_tle(result.verdict, result.timeout_expired):
                        break
                elif result.status == ExecStatus.ERROR:
                    result.verdict = Verdict.RUNTIME_ERROR
                    if config.args.error:
                        result.err = (
                            'Exited with code ' + str(result.returncode) + ':\n' + result.err
                        )
                    else:
                        result.err = 'Exited with code ' + str(result.returncode)
                    break

                result = self._validate_output(bar)
                if result is None:
                    bar.error(
                        f'No output validator found for testcase {self.testcase.name}',
                        resume=True,
                    )
                    result = ExecResult(
                        None, ExecStatus.REJECTED, 0, False, None, None, Verdict.VALIDATOR_CRASH
                    )
                elif result.status:
                    result.verdict = Verdict.ACCEPTED
                    validate.sanity_check(self.out_path, bar, strict_whitespace=False)
                elif result.status == ExecStatus.REJECTED:
                    result.verdict = Verdict.WRONG_ANSWER
                    if nextpass and nextpass.is_file():
                        bar.error(f'got WRONG_ANSWER but found nextpass.in', resume=True)
                        result.verdict = Verdict.VALIDATOR_CRASH
                else:
                    config.n_error += 1
                    result.verdict = Verdict.VALIDATOR_CRASH

                if result.verdict != Verdict.ACCEPTED:
                    break

                if not self._prepare_nextpass(nextpass):
                    break
                elif pass_id >= self.problem.limits.validation_passes:
                    bar.error(f'exceeded limit of validation_passes', resume=True)
                    result.verdict = Verdict.VALIDATOR_CRASH
                    break

                if interaction:
                    print('---', file=interaction)

            if interaction:
                interaction.close()

            if self.problem.multipass:
                result.pass_id = pass_id

            if tle_result is not None:
                result = tle_result

            result.duration = max_duration

            # Delete .out files larger than 1MB.
            if (
                not config.args.error
                and self.out_path.is_file()
                and self.out_path.stat().st_size > 1_000_000_000
            ):
                self.out_path.unlink()

        if result.verdict and (self.feedbackdir / 'nextpass.in').is_file():
            assert not self.problem.multipass
            bar.warn(f'Validator created nextpass.in for non multi-pass problem. Ignored.')

        self.result = result
        return result

    # check if we should continue after tle
    def _continue_with_tle(self, verdict, timeout_expired):
        if not self.problem.multipass:
            return False
        if verdict != Verdict.TIME_LIMIT_EXCEEDED:
            return False
        if timeout_expired:
            return False
        return any([config.args.verbose, config.args.all, config.args.action == 'all'])

    # prepare next pass
    def _prepare_nextpass(self, nextpass):
        if not nextpass or not nextpass.is_file():
            return False
        # clear all files outside of feedbackdir
        for f in self.tmpdir.iterdir():
            if f == self.feedbackdir:
                continue
            if f.is_file():
                f.unlink()
            elif f.exists():
                shutil.rmtree(f)
        # use nextpass.in as next input
        shutil.move(nextpass, self.in_path)
        return True

    def _validate_output(self, bar):
        output_validators = self.problem.validators(validate.OutputValidator)
        if output_validators is False or len(output_validators) == 0:
            return None
        assert len(output_validators) == 1
        validator = output_validators[0]

        flags = self.testcase.testdata_yaml_validator_flags(validator, bar)

        ret = validator.run(self.testcase, self, args=flags)

        judgemessage = self.feedbackdir / 'judgemessage.txt'
        judgeerror = self.feedbackdir / 'judgeerror.txt'
        if ret.err is None:
            ret.err = ''
        if judgeerror.is_file():
            ret.err = judgeerror.read_text(errors='replace')
        if len(ret.err) == 0 and judgemessage.is_file():
            ret.err = judgemessage.read_text(errors='replace')
        if ret.err:
            header = validator.name + ': ' if len(output_validators) > 1 else ''
            ret.err = header + ret.err

        return ret


class Submission(program.Program):
    def __init__(self, problem, path, skip_double_build_warning=False):
        super().__init__(
            problem, path, 'submissions', skip_double_build_warning=skip_double_build_warning
        )

        self.verdict = None
        self.duration = None

        # The first element will match the directory the file is in, if possible.
        self.expected_verdicts = self._get_expected_verdicts()

        # NOTE: Judging of interactive problems on systems without `os.wait4` is
        # suboptimal because we cannot determine which of the submission and
        # interactor exits first. Thus, we don't distinguish the different non-AC
        # verdicts.
        if self.problem.interactive and (is_windows() or is_bsd()):
            wrong_verdicts = [
                Verdict.WRONG_ANSWER,
                Verdict.TIME_LIMIT_EXCEEDED,
                Verdict.RUNTIME_ERROR,
            ]
            for wrong_verdict in wrong_verdicts:
                if wrong_verdict in self.expected_verdicts:
                    self.expected_verdicts += wrong_verdicts
                    break

    def _get_expected_verdicts(self) -> list[Verdict]:
        expected_verdicts = []

        # Look for '@EXPECTED_RESULTS@: ' in all source files. This should be followed by a comma separated list of the following:
        # - ACCEPTED / CORRECT
        # - WRONG_ANSWER / WRONG-ANSWER / NO-OUTPUT
        # - TIME_LIMIT_EXCEEDED / TIMELIMIT
        # - RUN_TIME_ERROR / RUN-ERROR
        # Matching is case insensitive and all source files are checked.
        key = '@EXPECTED_RESULTS@: '
        files = (
            [self.path]
            if self.path.is_file()
            else self.path.glob('**/*') if self.path.is_dir() else []
        )
        for f in files:
            if not f.is_file():
                continue
            try:
                text = f.read_text().upper()
                beginpos = text.index(key) + len(key)
                endpos = text.find('\n', beginpos)
                arguments = map(str.strip, text[beginpos:endpos].split(','))
                for arg in arguments:
                    try:
                        expected_verdicts.append(from_string_domjudge(arg))
                    except ValueError:
                        error(
                            f'@EXPECTED_RESULTS@: `{arg}` for submission {self.short_path} is not valid'
                        )
                        continue
                break
            except (UnicodeDecodeError, ValueError):
                # Skip binary files.
                # Skip files where the key does not occur.
                pass

        if len(self.path.parts) >= 3 and self.path.parts[-3] == 'submissions':
            # Submissions in any of config.VERDICTS should not have `@EXPECTED_RESULTS@: `, and vice versa.
            # See https://github.com/DOMjudge/domjudge/issues/1861
            subdir = self.short_path.parts[0]
            if subdir in config.SUBMISSION_DIRS:
                if len(expected_verdicts) != 0:
                    warn(f'@EXPECTED_RESULTS@ in submission {self.short_path} is ignored.')
                expected_verdicts = [from_string(subdir.upper())]
            else:
                if len(expected_verdicts) == 0:
                    error(
                        f'Submission {self.short_path} must have @EXPECTED_RESULTS@. Defaulting to ACCEPTED.'
                    )

        expected_verdicts.sort()
        return expected_verdicts or [Verdict.ACCEPTED]

    # Run submission on in_path, writing stdout to out_path or stdout if out_path is None.
    # args is used by SubmissionInvocation to pass on additional arguments.
    # Returns ExecResult
    # The `default_timeout` argument is used when a submission is run as a solution when
    # generating testcases.
    def run(self, in_path, out_path, crop=True, args=[], cwd=None, default_timeout=False):
        assert self.run_command is not None
        # Just for safety reasons, change the cwd.
        if cwd is None:
            cwd = self.tmpdir
        with in_path.open('rb') as inf:
            out_file = out_path.open('wb') if out_path else None

            # Print stderr to terminal is stdout is None, otherwise return its value.
            result = exec_command(
                self.run_command + args,
                crop=crop,
                stdin=inf,
                stdout=out_file,
                stderr=None if out_file is None else True,
                timeout=True if default_timeout else self.problem.settings.timeout,
                cwd=cwd,
            )
            if out_file:
                out_file.close()
            return result

    # Run this submission on all testcases that are given.
    # Returns (OK verdict, printed newline)
    def run_testcases(
        self, max_submission_name_len: int, verdict_table, testcases, *, needs_leading_newline
    ):
        runs = [Run(self.problem, self, testcase) for testcase in testcases]
        max_testcase_len = max(len(run.name) for run in runs)
        if self.problem.multipass:
            max_testcase_len += 2
        max_item_len = max_testcase_len + max_submission_name_len - len(self.name)
        padding_len = max_submission_name_len - len(self.name)
        run_until = RunUntil.FIRST_ERROR

        if (
            config.args.all == 1
            or config.args.verbose
            or config.args.action in ['all', 'timelimit']
        ):
            run_until = RunUntil.DURATION
        if config.args.all == 2 or config.args.reorder:
            run_until = RunUntil.ALL

        verdicts = Verdicts(
            testcases,
            self.problem.settings.timeout,
            run_until,
        )

        verdict_table.next_submission(verdicts)
        bar = verdict_table.ProgressBar(
            self.name,
            count=len(runs),
            max_len=max_item_len,
            needs_leading_newline=needs_leading_newline,
        )

        def process_run(run: Run):
            if not verdicts.run_is_needed(run.name):
                bar.skip()
                return

            localbar = bar.start(run)
            result = run.run(localbar)

            verdict_table.update_verdicts(run.name, result.verdict, result.duration)

            # Print stderr whenever something is printed
            if result.out and result.err:
                output_type = 'PROGRAM STDERR' if self.problem.interactive else 'STDOUT'
                data = (
                    f'STDERR:'
                    + localbar._format_data(result.err)
                    + f'\n{output_type}:'
                    + localbar._format_data(result.out)
                    + '\n'
                )
            else:
                data = ''
                if result.err:
                    data = crop_output(result.err)
                if result.out:
                    data = crop_output(result.out)

            judgemessage = run.feedbackdir / 'judgemessage.txt'
            judgeerror = run.feedbackdir / 'judgeerror.txt'
            # Add data from feedbackdir.
            for f in run.feedbackdir.iterdir():
                if f in [judgemessage, judgeerror]:
                    continue
                if f.name.startswith('.'):
                    continue  # skip "hidden" files
                if not f.is_file():
                    localbar.warn(f"Validator wrote to {f} but it's not a file.")
                    continue
                try:
                    t = f.read_text()
                except UnicodeDecodeError:
                    localbar.warn(
                        f'Validator wrote to {f} but it cannot be parsed as unicode text.'
                    )
                    continue
                if not t:
                    continue
                if len(data) > 0 and data[-1] != '\n':
                    data += '\n'
                data += f'{f.name}:' + localbar._format_data(t) + '\n'

            got_expected = result.verdict in [Verdict.ACCEPTED] + self.expected_verdicts

            if result.verdict == Verdict.ACCEPTED:
                color = f'{Style.DIM}'
            else:
                color = Fore.GREEN if got_expected else Fore.RED
            timeout = result.duration >= self.problem.settings.timeout
            duration_style = Style.BRIGHT if timeout else ''
            passmsg = (
                f':{Fore.CYAN}{result.pass_id}{Style.RESET_ALL}' if self.problem.multipass else ''
            )
            testcase = f'{run.name}{Style.RESET_ALL}{passmsg}'
            style_len = len(f'{Style.RESET_ALL}')
            message = f'{color}{result.verdict.short():>3}{duration_style}{result.duration:6.3f}s{Style.RESET_ALL} {Style.DIM}@ {testcase:{max_testcase_len+style_len}}'

            # Update padding since we already print the testcase name after the verdict.
            localbar.item_width = padding_len
            localbar.done(got_expected, message, data, print_item=False)

        p = parallel.new_queue(process_run, pin=True)
        for run in runs:
            p.put(run)
        p.done()

        self.verdict = verdicts['.']
        assert isinstance(self.verdict, Verdict), "Verdict of root must not be empty"

        # Use a bold summary line if things were printed before.
        if bar.logged:
            color = (
                Style.BRIGHT + Fore.GREEN
                if self.verdict in self.expected_verdicts
                else Style.BRIGHT + Fore.RED
            )
        else:
            color = Fore.GREEN if self.verdict in self.expected_verdicts else Fore.RED

        (salient_testcase, salient_duration) = verdicts.salient_testcase()
        salient_print_verdict = self.verdict
        salient_duration_style = (
            Style.BRIGHT if salient_duration >= self.problem.settings.timeout else ''
        )

        # Summary line is the only thing shown.
        message = f'{color}{salient_print_verdict.short():>3}{salient_duration_style}{salient_duration:6.3f}s{Style.RESET_ALL} {Style.DIM}@ {salient_testcase:{max_testcase_len}}{Style.RESET_ALL}'

        if verdicts.run_until in [RunUntil.DURATION, RunUntil.ALL]:
            slowest_pair = verdicts.slowest_testcase()
            assert slowest_pair is not None
            (slowest_testcase, slowest_duration) = slowest_pair
            slowest_verdict = verdicts[slowest_testcase]
            assert isinstance(
                slowest_verdict, Verdict
            ), "Verdict of slowest testcase must not be empty"

            slowest_color = (
                Fore.GREEN
                if slowest_verdict == Verdict.ACCEPTED or slowest_verdict in self.expected_verdicts
                else Fore.RED
            )

            slowest_duration_style = (
                Style.BRIGHT if slowest_duration >= self.problem.settings.timeout else ''
            )

            message += f' {Style.DIM}{Fore.CYAN}slowest{Fore.RESET}:{Style.RESET_ALL} {slowest_color}{slowest_verdict.short():>3}{slowest_duration_style}{slowest_duration:6.3f}s{Style.RESET_ALL} {Style.DIM}@ {slowest_testcase}{Style.RESET_ALL}'

        bar.item_width -= max_testcase_len + 1
        printed_newline = bar.finalize(message=message, suppress_newline=config.args.tree)
        if config.args.tree:
            verdict_table.print(force=True, new_lines=0)
            verdict_table.last_printed = []
            print(file=sys.stderr)
            printed_newline = True

        return self.verdict in self.expected_verdicts, printed_newline

    def test(self):
        print(ProgressBar.action('Running', str(self.name)), file=sys.stderr)

        testcases = self.problem.testcases(needans=False)

        if self.problem.interactive:
            output_validators = self.problem.validators(validate.OutputValidator)
            if output_validators is False:
                return

        for testcase in testcases:
            header = ProgressBar.action('Running ' + str(self.name), testcase.name)
            print(header, file=sys.stderr)

            if not self.problem.interactive:
                assert self.run_command is not None
                with testcase.in_path.open('rb') as inf:
                    result = exec_command(
                        self.run_command,
                        crop=False,
                        stdin=inf,
                        stdout=None,
                        stderr=None,
                        timeout=self.problem.settings.timeout,
                    )

                assert result.err is None and result.out is None
                if result.duration >= self.problem.settings.timeout:
                    status = f'{Fore.RED}Aborted!'
                    config.n_error += 1
                elif not result.status and result.status != ExecStatus.TIMEOUT:
                    config.n_error += 1
                    status = None
                    print(
                        f'{Fore.RED}Run time error!{Style.RESET_ALL} exit code {result.returncode} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}',
                        file=sys.stderr,
                    )
                elif (
                    result.duration > self.problem.settings.timelimit
                    or result.status == ExecStatus.TIMEOUT
                ):
                    status = f'{Fore.YELLOW}Done (TLE):'
                    config.n_warn += 1
                else:
                    status = f'{Fore.GREEN}Done:'

                if status:
                    print(
                        f'{status}{Style.RESET_ALL} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}',
                        file=sys.stderr,
                    )
                print(file=sys.stderr)

            else:
                # Interactive problem.
                run = Run(self.problem, self, testcase)
                result = interactive.run_interactive_testcase(
                    run, interaction=True, validator_error=None, team_error=None
                )
                if result.verdict != Verdict.ACCEPTED:
                    config.n_error += 1
                    print(
                        f'{Fore.RED}{result.verdict}{Style.RESET_ALL} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}',
                        file=sys.stderr,
                    )
                else:
                    print(
                        f'{Fore.GREEN}{result.verdict}{Style.RESET_ALL} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}',
                        file=sys.stderr,
                    )

    # Run the submission using stdin as input.
    def test_interactive(self):
        if self.problem.interactive:
            output_validators = self.problem.validators(validate.OutputValidator)
            if output_validators is False:
                return

        bar = ProgressBar('Running ' + str(self.name), max_len=1, count=1)
        bar.start()
        # print(ProgressBar.action('Running', str(self.name)), file=sys.stderr)

        is_tty = sys.stdin.isatty()

        tc = 0
        while True:
            tc += 1
            name = f'run {tc}'
            bar.update(1, len(name))
            bar.start(name)
            # Reinitialize the underlying program, so that changed to the source
            # code can be picked up in build.
            super().__init__(self.problem, self.path, self.subdir, skip_double_build_warning=True)
            bar.log('from stdin' if is_tty else 'from file')

            # Launch a separate thread to pass stdin to a pipe.
            r, w = os.pipe()
            ok = True
            eof = False

            TEE_CODE = R'''
import sys
while True:
    l = sys.stdin.read(1)
    if l=='': break
    sys.stdout.write(l)
    sys.stdout.flush()
'''
            writer = None

            # Wait for first input
            try:
                read = False
                for l in sys.stdin:
                    read = True
                    # Read the first line of input, and re-build the program if
                    # needed after the first line has been entered.
                    if not self.build(bar):
                        return
                    os.write(w, bytes(l, 'utf8'))
                    break
                if not read:
                    return

                writer = subprocess.Popen(['python3', '-c', TEE_CODE], stdin=None, stdout=w)

                assert self.run_command is not None
                result = exec_command(
                    self.run_command, crop=False, stdin=r, stdout=None, stderr=None, timeout=None
                )

                assert result.err is None and result.out is None
                if not result.status:
                    config.n_error += 1
                    status = None
                    print(
                        f'{Fore.RED}Run time error!{Style.RESET_ALL} exit code {result.returncode} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}',
                        file=sys.stderr,
                    )
                else:
                    status = f'{Fore.GREEN}Done:'

                if status:
                    print(
                        f'{status}{Style.RESET_ALL} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}',
                        file=sys.stderr,
                    )
                print(file=sys.stderr)
            finally:
                os.close(r)
                os.close(w)
                if writer:
                    writer.kill()
            bar.done()

            if not is_tty:
                break
