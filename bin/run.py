import program
import config
import validate
import interactive

from util import *

class Testcase:
    def __init__(self, problem, path, *, short_path = None):
        assert path.suffix == '.in'

        self.problem = problem

        self.in_path = path.resolve()
        self.ans_path = path.resolve().with_suffix('.ans')
        # Note: testcases outside problem/data must pass in the short_path explicitly.
        if short_path is None:
            self.short_path = path.relative_to(problem.path / 'data')
        else:
            assert short_path is not None
            self.short_path = short_path

        # Display name: everything after data/.
        self.name = str(self.short_path.with_suffix(''))

        bad = self.short_path.parts[0] == 'bad'
        self.bad_input = bad and not self.ans_path.is_file()
        self.bad_output = bad and self.ans_path.is_file()

    def with_suffix(self, ext):
        return self.in_path.with_suffix(ext)

    # Validate the testcase input/output format. validator_type must be 'input_format' or 'output_format'.
    def validate_format(self, validator_type,
                          *,
                          bar,
                          constraints=None):
        assert validator_type in ['input_format', 'output_format']

        bad_testcase = self.bad_input if validator_type == 'input_format' else self.bad_output

        success = True

        validators = self.problem.validators(validator_type, check_constraints=constraints != None)
        if validators == False:
            return True

        for validator in validators:
            ret = validator.run(self, constraints)

            success &= ret.ok
            message = ''

            # Failure?
            if ret.ok:
                message = 'PASSED ' + validator.name
            else:
                message = 'FAILED ' + validator.name

            # Print stdout and stderr whenever something is printed
            if not ret.err: err = ''
            if ret.out and config.args.error:
                ret.out = f'\n{cc.red}VALIDATOR STDOUT{cc.reset}\n' + cc.orange + ret.out
            else:
                ret.out = ''

            bar.part_done(ret.ok, message, data=ret.err +ret.out)

            if not ret.ok:
                # Move testcase to destination directory if specified.
                if hasattr(config.args, 'move_to') and config.args.move_to:
                    infile = testcase.in_path
                    targetdir = problem / config.args.move_to
                    targetdir.mkdir(parents=True, exist_ok=True)
                    intarget = targetdir / infile.name
                    infile.rename(intarget)
                    bar.warn('Moved to ' + print_name(intarget))
                    ansfile = testcase.ans_path
                    if ansfile.is_file():
                        if validator_type == 'input':
                            ansfile.unlink()
                            bar.warn('Deleted ' + print_name(ansfile))
                        if validator_type == 'output':
                            anstarget = intarget.with_suffix('.ans')
                            ansfile.rename(anstarget)
                            bar.warn('Moved to ' + print_name(anstarget))
                    break

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

        tmp_path = config.tmpdir / self.problem.name / 'runs' / self.submission.short_path / self.testcase.short_path
        self.out_path = tmp_path.with_suffix('.out')
        self.feedbackdir = tmp_path.with_suffix('.feedbackdir')
        self.feedbackdir.mkdir(exist_ok=True, parents=True)

    # Return an ExecResult object amended with verdict.
    def run(self, *, interaction=None, submission_args=None):
        if self.problem.interactive:
            result = interactive.run_interactive_testcase(self, interaction=interaction, submission_args=submission_args)
        else:
            result = self.submission.run(self.testcase.in_path, self.out_path)
            if result.duration > self.problem.settings.timelimit:
                result.verdict = 'TIME_LIMIT_EXCEEDED'
            elif result.ok is not True:
                result.verdict = 'RUN_TIME_ERROR'
                result.err = 'Exited with code ' + str(result.ok) + ':\n' + result.err
            else:
                result = self._validate_output()

                if result.ok is True:
                    result.verdict = 'ACCEPTED'
                elif result.ok is False:
                    result.verdict = 'WRONG_ANSWER'
                else:
                    config.n_error += 1
                    result.verdict = 'VALIDATOR_CRASH'

        self.result = result
        return result


    def _validate_output(self):
        flags = self.problem.settings.validator_flags

        output_validators = self.problem.validators('output')

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

            if ret.ok != True:
                return ret

            last_result = ret

        return last_result


class Submission(program.Program):
    subdir = 'submissions'
    def __init__(self, problem, path):
        super().__init__(problem, path)

        subdir = self.short_path.parts[0]
        self.expected_verdict = subdir.upper() if subdir.upper() in config.VERDICTS else None
        self.verdict = None
        self.duration = None

    # Run submission on in_path, writing stdout to out_path or stdout if out_path is None.
    # args is used by SubmissionInvocation to pass on additional arguments.
    # Returns ExecResult
    def run(self, in_path, out_path, crop=True, args=[], cwd=None):
        assert self.run_command is not None
        # Just for safety reasons, change the cwd.
        if cwd is None: cwd = out_path.parent
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
    # Returns the final verdict.
    def run_all_testcases(self, max_submission_name_len=None, table_dict=None):
        runs = [Run(self.problem, self, testcase) for testcase in self.problem.testcases()]
        max_item_len = max(len(run.name) for run in runs) + max_submission_name_len - len(self.name) - 1
        bar = ProgressBar('Running ' + self.name, max_len = max_item_len)

        max_duration = 0

        verdict = (config.PRIORITY['ACCEPTED'], 'ACCEPTED', 0) # priority, verdict, duration
        verdict_run = None

        # TODO: Run multiple runs in parallel.
        for run in runs:
            bar.start(run)
            result = run.run()

            new_verdict = (config.PRIORITY[result.verdict], result.verdict, result.duration)
            if  new_verdict > verdict:
                verdict= new_verdict
                verdict_run = run
            max_duration = max(max_duration, result.duration)

            if table_dict is not None:
                table_dict[run.name] = result.verdict == 'ACCEPTED'

            got_expected = result.verdict == 'ACCEPTED' or result.verdict == self.expected_verdict

            # Print stderr whenever something is printed
            if result.out and result.err:
                output_type = 'PROGRAM STDERR' if self.problem.interactive else 'STDOUT'
                data = f'STDERR:' + util.ProgresBar._format_data(result.err) + '\n{output_type}:' + util.ProgressBar._format_data(result.out) + '\n'
            else:
                data = result.err

            bar.done(got_expected, f'{result.duration:6.3f}s {result.verdict}', data)

            # Lazy judging: stop on the first error when not in verbose mode.
            if not config.args.verbose and result.verdict in config.MAX_PRIORITY_VERDICT:
                bar.count = None
                break

        self.verdict = verdict[1]
        self.duration = max_duration

        # Use a bold summary line if things were printed before.
        if bar.logged:
            color = cc.boldgreen if self.verdict == self.expected_verdict else cc.boldred
            boldcolor = cc.bold
        else:
            color = cc.green if self.verdict == self.expected_verdict else cc.red
            boldcolor = ''

        bar.finalize(message=f'{max_duration:6.3f}s {color}{verdict[1]:<20}{cc.reset} @ {verdict_run.testcase.name}')

        if config.args.verbose:
            print()

        return self.verdict == self.expected_verdict







# TODO: Migrate these TEST subcommands into submission as well.
# TODO: Figure out what exactly to do with this. It's somewhat messy.
def _test_submission(problem, submission, testcases, settings):
    print(ProgressBar.action('Running', str(submission[0])))

    if problem.interactive:
        output_validators = validate.get_validators(problem, 'output')
        if len(output_validators) != 1:
            error(
                'Interactive problems need exactly one output validator. Found {len(output_validators)}.'
            )
            return False

    time_limit, timeout = get_time_limits(settings)
    for testcase in testcases:
        header = ProgressBar.action('Running ' + str(submission[0]), testcase.name)
        print(header)

        if not problem.interactive:
            # err and out should be None because they go to the terminal.
            ok, duration, err, out = run_testcase(submission[1],
                                                  testcase,
                                                  outfile=None,
                                                  timeout=timeout,
                                                  crop=False)
            did_timeout = duration > time_limit
            assert err is None and out is None
            if ok is not True:
                config.n_error += 1
                print(
                    f'{cc.red}Run time error!{cc.reset} exit code {ok} {cc.bold}{duration:6.3f}s{cc.reset}'
                )
            elif did_timeout:
                config.n_error += 1
                print(f'{cc.red}Aborted!{cc.reset} {cc.bold}{duration:6.3f}s{cc.reset}')
            else:
                print(f'{cc.green}Done:{cc.reset} {cc.bold}{duration:6.3f}s{cc.reset}')
            print()

        else:
            # Interactive problem.
            verdict, duration, val_err, team_err = process_interactive_testcase(
                submission[1],
                testcase,
                settings,
                output_validators,
                interaction=True,
                validator_error=None,
                team_error=None)
            if verdict != 'ACCEPTED':
                config.n_error += 1
                print(f'{cc.red}{verdict}{cc.reset} {cc.bold}{duration:6.3f}s{cc.reset}')
            else:
                print(f'{cc.green}{verdict}{cc.reset} {cc.bold}{duration:6.3f}s{cc.reset}')


# Takes a list of submissions and runs them against the chosen testcases.
# Instead of validating the output, this function just prints all output to the
# terminal.
# Note: The CLI only accepts one submission.
def test_submissions(problem, settings):
    testcases = problem.testcases(needans=False)

    if len(testcases) == 0:
        warn('No testcases found!')
        return False

    submissions = _get_submissions(problem.path)

    verdict_table = []
    for verdict in submissions:
        for submission in submissions[verdict]:
            _test_submission(problem.path, submission, testcases, settings)
    return True
