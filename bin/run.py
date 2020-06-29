import program
import config
import validate
import interactive
import os

from util import *


class Testcase:
    def __init__(self, problem, path, *, short_path=None):
        assert path.suffix == '.in'

        self.problem = problem

        self.in_path = path
        self.ans_path = self.in_path.with_suffix('.ans')
        # Note: testcases outside problem/data must pass in the short_path explicitly.
        if short_path is None:
            try:
                self.short_path = path.relative_to(problem.path / 'data')
            except ValueError:
                fatal(f"Testcase {path} is not inside {problem.path / 'data'}.")
        else:
            assert short_path is not None
            self.short_path = short_path

        # Display name: everything after data/.
        self.name = str(self.short_path.with_suffix(''))

        bad = self.short_path.parts[0] == 'bad'
        self.bad_input = bad and not self.ans_path.is_file()
        self.bad_output = bad and self.ans_path.is_file()

        self.sample = self.short_path.parts[0] == 'sample'

        self.included = False
        if path.is_symlink():
            include_target = Path(os.path.normpath(path.parent / os.readlink(path)))
            try:
                include_target.relative_to(problem.path / 'data')
                self.included = True
            except ValueError:
                # The case is a manual cases included from generators/.
                pass

    def with_suffix(self, ext):
        return self.in_path.with_suffix(ext)

    # Validate the testcase input/output format. validator_type must be 'input_format' or 'output_format'.
    def validate_format(self, validator_type, *, bar, constraints=None):
        assert validator_type in ['input_format', 'output_format']

        bad_testcase = self.bad_input if validator_type == 'input_format' else self.bad_output

        success = True

        validators = self.problem.validators(validator_type, check_constraints=constraints != None)
        if validators == False:
            return True

        for validator in validators:
            ret = validator.run(self, constraints=constraints)

            success &= ret.ok is True
            message = ''

            # Failure?
            if ret.ok is True:
                message = 'Passed ' + validator.name
            else:
                message = 'Failed ' + validator.name

            # Print stdout and stderr whenever something is printed
            data = ''
            if ret.ok is not True or config.args.error:
                if ret.err and ret.out:
                    ret.out = ret.err + f'\n{cc.red}VALIDATOR STDOUT{cc.reset}\n' + cc.orange + ret.out
                elif ret.err: data = ret.err
                elif ret.out: data = ret.out
            else:
                data = ret.err

            bar.part_done(ret.ok is True, message, data=data)

            if ret.ok is True: continue

            # Move testcase to destination directory if specified.
            if hasattr(config.args, 'move_to') and config.args.move_to:
                infile = testcase.in_path
                targetdir = problem / config.args.move_to
                targetdir.mkdir(parents=True, exist_ok=True)
                intarget = targetdir / infile.name
                infile.rename(intarget)
                bar.log('Moved to ' + print_name(intarget))
                ansfile = testcase.ans_path
                if ansfile.is_file():
                    if validator_type == 'input':
                        ansfile.unlink()
                        bar.log('Deleted ' + print_name(ansfile))
                    if validator_type == 'output':
                        anstarget = intarget.with_suffix('.ans')
                        ansfile.rename(anstarget)
                        bar.log('Moved to ' + print_name(anstarget))

            # Remove testcase if specified.
            elif validator_type == 'input' and hasattr(config.args,
                                                       'remove') and config.args.remove:
                bar.log(cc.red + 'REMOVING TESTCASE!' + cc.reset)
                if testcase.in_path.exists():
                    testcase.in_path.unlink()
                if testcase.ans_path.exists():
                    testcase.ans_path.unlink()

            break

        return success


class Run:
    def __init__(self, problem, submission, testcase):
        self.problem = problem
        self.submission = submission
        self.testcase = testcase
        self.name = self.testcase.name
        self.result = None

        tmp_path = self.problem.tmpdir / 'runs' / self.submission.short_path / self.testcase.short_path
        self.out_path = tmp_path.with_suffix('.out')
        self.feedbackdir = tmp_path.with_suffix('.feedbackdir')
        self.feedbackdir.mkdir(exist_ok=True, parents=True)

    # Return an ExecResult object amended with verdict.
    def run(self, *, interaction=None, submission_args=None):
        if self.problem.interactive:
            result = interactive.run_interactive_testcase(self,
                                                          interaction=interaction,
                                                          submission_args=submission_args)
        else:
            result = self.submission.run(self.testcase.in_path, self.out_path)
            if result.duration > self.problem.settings.timelimit:
                result.verdict = 'TIME_LIMIT_EXCEEDED'
                if result.duration >= self.problem.settings.timeout:
                    result.print_verdict_ = 'TLE (aborted)'
            elif result.ok is not True:
                result.verdict = 'RUN_TIME_ERROR'
                if config.args.error:
                    result.err = 'Exited with code ' + str(result.ok) + ':\n' + result.err
                else:
                    result.err = 'Exited with code ' + str(result.ok)
            else:
                # Overwrite the result with validator returncode and stdout/stderr, but keep the original duration.
                duration = result.duration
                result = self._validate_output()
                result.duration = duration

                if result.ok is True:
                    result.verdict = 'ACCEPTED'
                elif result.ok is False:
                    result.verdict = 'WRONG_ANSWER'
                else:
                    config.n_error += 1
                    result.verdict = 'VALIDATOR_CRASH'

            # Delete .out files larger than 1MB.
            if not config.args.error and self.out_path.is_file() and self.out_path.stat().st_size > 1000000000:
                self.out_path.unlink()

        self.result = result
        return result

    def _validate_output(self):
        output_validators = self.problem.validators('output')
        if output_validators is False: return False

        last_result = None
        for output_validator in output_validators:
            ret = output_validator.run(self.testcase, self)

            judgemessage = self.feedbackdir / 'judgemessage.txt'
            judgeerror = self.feedbackdir / 'judgeerror.txt'
            if ret.err is None:
                ret.err = ''
            if judgemessage.is_file():
                ret.err += judgemessage.read_text()
                judgemessage.unlink()
            if judgeerror.is_file():
                # Remove any std output because it will usually only contain the
                ret.err = judgeerror.read_text()
                judgeerror.unlink()
            if ret.err:
                header = output_validator.name + ': ' if len(output_validators) > 1 else ''
                ret.err = header + ret.err

            if ret.ok == config.RTV_WA:
                ret.ok = False

            if ret.ok is not True:
                return ret

            last_result = ret

        return last_result


class Submission(program.Program):
    subdir = 'submissions'

    def __init__(self, problem, path, skip_double_build_warning=False):
        super().__init__(problem, path, skip_double_build_warning=skip_double_build_warning)

        self.verdict = None
        self.duration = None

        # The first element will match the directory the file is in, if possible.
        self.expected_verdicts = self._get_expected_verdicts()

    def _get_expected_verdicts(self):
        verdicts = []

        # Look for '@EXPECTED_RESULTS@: ' in all source files. This should be followed by a comma separated list of the following:
        # - ACCEPTED / CORRECT
        # - WRONG_ANSWER / WRONG-ANSWER / NO-OUTPUT
        # - TIME_LIMIT_EXCEEDED / TIMELIMIT
        # - RUN_TIME_ERROR / RUN-ERROR
        domjudge_verdict_map = {'CORRECT': 'ACCEPTED', 'WRONG-ANSWER': 'WRONG_ANSWER', 'TIMELIMIT': 'TIME_LIMIT_EXCEEDED', 'RUN-ERROR': 'RUN_TIME_ERROR', 'NO-OUTPUT': 'WRONG_ANSWER', 'CHECK-MANUALLY': None, 'COMPILER-ERROR': None}
        # Matching is case insensitive and all source files are checked.
        key = '@EXPECTED_RESULTS@: '
        if self.path.is_file():
            files = [self.path]
        elif self.path.is_dir():
            files = self.path.glob('**/*')
        else:
            files = []
        for f in files:
            if not f.is_file(): continue
            try:
                text = f.read_text().upper()
                beginpos = text.index(key) + len(key)
                endpos = text.find('\n', beginpos)
                arguments = map(str.strip, text[beginpos:endpos].split(','))
                for arg in arguments:
                    if arg in domjudge_verdict_map:
                        arg = domjudge_verdict_map[arg]
                        if arg is None:
                            continue
                    if arg not in config.VERDICTS:
                        error(f'@EXPECTED_RESULT@ {arg} for submission {self.short_path} is not valid')
                        continue
                    verdicts.append(arg)
                break
            except (UnicodeDecodeError, ValueError):
                # Skip binary files.
                # Skip files where the key does not occur.
                pass

        subdir = self.short_path.parts[0].upper()
        if subdir in config.VERDICTS:
            if len(verdicts) > 0 and subdir not in verdicts:
                error(f'Submission {self.short_path} must have implicit verdict {subdir} listed in @EXPECTED_RESULTS@.')
                verdicts = [subdir] + verdicts
            elif len(verdicts) == 0:
                verdicts = [subdir]

        if len(verdicts) == 0:
            verdicts = ['ACCEPTED']
        return verdicts

    # Run submission on in_path, writing stdout to out_path or stdout if out_path is None.
    # args is used by SubmissionInvocation to pass on additional arguments.
    # Returns ExecResult
    def run(self, in_path, out_path, crop=True, args=[], cwd=None):
        assert self.run_command is not None
        # Just for safety reasons, change the cwd.
        if cwd is None: cwd = self.tmpdir
        with in_path.open('rb') as inf:
            out_file = out_path.open('wb') if out_path else None

            # Print stderr to terminal is stdout is None, otherwise return its value.
            result = exec_command(self.run_command + args,
                                  crop=crop,
                                  stdin=inf,
                                  stdout=out_file,
                                  stderr=None if out_file is None else True,
                                  timeout=self.problem.settings.timeout,
                                  cwd=cwd)
            if out_file: out_file.close()
            return result

    # Run this submission on all testcases for the current problem.
    # Returns (OK verdict, printed newline)
    def run_all_testcases(self,
                          max_submission_name_len=None,
                          table_dict=None,
                          *,
                          needs_leading_newline):
        runs = [Run(self.problem, self, testcase) for testcase in self.problem.testcases()]
        max_item_len = max(len(run.name)
                           for run in runs) + max_submission_name_len - len(self.name)

        bar = ProgressBar('Running ' + self.name,
                          count=len(runs),
                          max_len=max_item_len,
                          needs_leading_newline=needs_leading_newline)

        max_duration = -1

        verdict = (-100, 'ACCEPTED', 'ACCEPTED', 0)  # priority, verdict, print_verdict, duration
        verdict_run = None

        # TODO: Run multiple runs in parallel.
        for run in runs:
            bar.start(run)
            result = run.run()

            new_verdict = (config.PRIORITY[result.verdict], result.verdict, result.print_verdict(), result.duration)
            if new_verdict > verdict:
                verdict = new_verdict
                verdict_run = run
            max_duration = max(max_duration, result.duration)

            if table_dict is not None:
                table_dict[run.name] = result.verdict == 'ACCEPTED'

            got_expected = result.verdict in ['ACCEPTED'] + self.expected_verdicts

            # Print stderr whenever something is printed
            if result.out and result.err:
                output_type = 'PROGRAM STDERR' if self.problem.interactive else 'STDOUT'
                data = f'STDERR:' + bar._format_data(
                    result.err) + f'\n{output_type}:' + bar._format_data(
                        result.out) + '\n'
            else:
                data = ''
                if result.err:
                    data = result.err
                if result.out:
                    data = result.out

            bar.done(got_expected, f'{result.duration:6.3f}s {result.print_verdict()}', data)

            # Lazy judging: stop on the first error when not in verbose mode.
            if not config.args.verbose and result.verdict in config.MAX_PRIORITY_VERDICT:
                bar.count = None
                break

        self.verdict = verdict[1]
        self.print_verdict = verdict[2]
        self.duration = max_duration

        # Use a bold summary line if things were printed before.
        if bar.logged:
            color = cc.boldgreen if self.verdict in self.expected_verdicts else cc.boldred
            boldcolor = cc.bold
        else:
            color = cc.green if self.verdict in self.expected_verdicts else cc.red
            boldcolor = ''

        printed_newline = bar.finalize(
            message=
            f'{max_duration:6.3f}s {color}{self.print_verdict:<20}{cc.reset} @ {verdict_run.testcase.name}'
        )

        return (self.verdict in self.expected_verdicts, printed_newline)

    def test(self):
        print(ProgressBar.action('Running', str(self.name)))

        testcases = self.problem.testcases(needans=False)

        if self.problem.interactive:
            output_validators = self.problem.validators('output')
            if output_validators is False:
                return

        for testcase in testcases:
            header = ProgressBar.action('Running ' + str(self.name), testcase.name)
            print(header)

            if not self.problem.interactive:
                assert self.run_command is not None
                with testcase.in_path.open('rb') as inf:
                    result = exec_command(self.run_command,
                                          crop=False,
                                          stdin=inf,
                                          stdout=None,
                                          stderr=None,
                                          timeout=self.problem.settings.timeout)

                assert result.err is None and result.out is None
                if result.duration > self.problem.settings.timeout:
                    status = f'{cc.red}Aborted!'
                    config.n_error += 1
                elif result.ok is not True and result.ok != -9:
                    config.n_error += 1
                    status = None
                    print(
                        f'{cc.red}Run time error!{cc.reset} exit code {result.ok} {cc.bold}{result.duration:6.3f}s{cc.reset}'
                    )
                elif result.duration > self.problem.settings.timelimit:
                    status = f'{cc.orange}Done (TLE):'
                    config.n_warn += 1
                else:
                    status = f'{cc.green}Done:'

                if status:
                    print(f'{status}{cc.reset} {cc.bold}{result.duration:6.3f}s{cc.reset}')
                print()

            else:
                # Interactive problem.
                run = Run(self.problem, self, testcase)
                result = interactive.run_interactive_testcase(run,
                                                              interaction=True,
                                                              validator_error=None,
                                                              team_error=None)
                if result.verdict != 'ACCEPTED':
                    config.n_error += 1
                    print(
                        f'{cc.red}{result.verdict}{cc.reset} {cc.bold}{result.duration:6.3f}s{cc.reset}'
                    )
                else:
                    print(
                        f'{cc.green}{result.verdict}{cc.reset} {cc.bold}{result.duration:6.3f}s{cc.reset}'
                    )
