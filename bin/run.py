import os
import sys

import config
import validate
import program
import interactive
import parallel

from util import *
from colorama import Fore, Style


class Testcase:
    # Testcases outside problem/data must pass in the short_path explicitly.
    # In that case, `path` is the (absolute) path to the `.in` file being
    # tested, and `short_path` is the name of the testcase relative to
    # `problem.path / 'data'`.
    def __init__(self, problem, path, *, short_path=None):
        assert path.suffix == '.in' or path.suffixes == [".in", ".statement"]

        self.problem = problem

        self.in_path = path
        self.ans_path = (
            self.in_path.with_suffix('.ans')
            if path.suffix == '.in'
            else self.in_path.with_name(self.in_path.with_suffix('').stem + '.ans.statement')
        )
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

        self.bad_input = self.short_path.parts[0] == 'invalid_inputs'
        self.bad_output = self.short_path.parts[0] == 'invalid_outputs'

        # Backwards compatibility support for `data/bad`.
        if self.short_path.parts[0] == 'bad':
            self.bad_input = not self.ans_path.is_file()
            self.bad_output = self.ans_path.is_file()

        self.sample = self.short_path.parts[0] == 'sample'

        self.included = False
        if path.is_symlink():
            include_target = Path(os.path.normpath(path.parent / os.readlink(path)))
            if is_relative_to(problem.path / 'data', include_target):
                self.included = True
            else:
                # The case is an unlisted cases included from generators/.
                pass

        # Get the testdata.yaml content for this testcase.
        # Read using the short_path instead of the in_path, because during
        # generate the testcase will live in a temporary directory, where
        # testdata.yaml doesn't exist.
        self.testdata_yaml = problem.get_testdata_yaml(self.problem.path / 'data' / self.short_path)

    def with_suffix(self, ext):
        return self.in_path.with_suffix(ext)

    # Return the flags specified in testdata.yaml for the given validator,
    # None if no flags were found, or False if this validator should be skipped.
    # If `split`, split the string by spaces.
    def testdata_yaml_validator_flags(self, validator_type, validator, split=True):
        # Do not use flags when using the default output validator.
        if self.problem.settings.validation == 'default' and validator_type == 'output':
            return None

        if self.testdata_yaml is None:
            return None
        key = (
            'input_validator_flags'
            if validator_type == 'input'
            else 'output_validator_flags'
        )
        if key not in self.testdata_yaml:
            return None
        flags = self.testdata_yaml[key]
        # Note: support for lists/dicts for was removed in #259.
        if not isinstance(flags, str):
            fatal(f'{key} must be a string in testdata.yaml')
        return flags.split() if split else flags

    # Returns a dict of objects
    # hash =>
    # - name
    # - flags
    # - hash
    # indicating which validators will be run for the current testcase.
    def validator_hashes(self, validator_type):
        assert validator_type in ['input', 'answer']
        validators = self.problem.validators(validator_type) or []

        d = dict()

        for validator in validators:
            flags = self.testdata_yaml_validator_flags(validator_type, validator, split=False)
            if flags is False:
                continue
            o = {
                'name': validator.name,
                'flags': flags,
                'hash': validator.hash,
            }
            h = combine_hashes_dict(o)
            # Don't actually store the somewhat useless validator hash.
            del o['hash']
            d[h] = o

        return d

    # Validate the testcase input/output format. validator_type must be 'input' or 'answer'.
    def validate_format(
        self, validator_type, *, bar, constraints=None, warn_instead_of_error=False
    ):
        assert validator_type in ['input', 'answer', 'output']

        bad_testcase = self.bad_input if validator_type == 'input' else self.bad_output

        success = True

        validators = self.problem.validators(validator_type, check_constraints=constraints != None)
        if validators == False:
            return True

        for validator in validators:
            flags = self.testdata_yaml_validator_flags(validator_type, validator)
            if flags is False:
                continue

            ret = validator.run(self, constraints=None if bad_testcase else constraints, args=flags)

            success &= ret.ok is True
            message = ''

            # Failure?
            if ret.ok is True:
                message = validator.name + ' passed'
            else:
                message = validator.name + ' failed'

            # Print stdout and stderr whenever something is printed
            data = ''
            if ret.ok is not True or config.args.error:
                if ret.err and ret.out:
                    ret.out = (
                        ret.err
                        + f'\n{Fore.RED}VALIDATOR STDOUT{Style.RESET_ALL}\n'
                        + Fore.YELLOW
                        + ret.out
                    )
                elif ret.err:
                    data = ret.err
                elif ret.out:
                    data = ret.out

                if validator_type == 'input':
                    file = self.in_path
                if validator_type == 'answer':
                    file = self.ans_path
                data += (
                    f'{Style.RESET_ALL}-> {shorten_path(self.problem, file.parent) / file.name}\n'
                )
            else:
                data = ret.err

            bar.part_done(
                ret.ok is True, message, data=data, warn_instead_of_error=warn_instead_of_error
            )

            if ret.ok is True:
                continue

            # Move testcase to destination directory if specified.
            if config.args.move_to:
                infile = self.in_path
                targetdir = self.problem.path / config.args.move_to
                targetdir.mkdir(parents=True, exist_ok=True)
                intarget = targetdir / infile.name
                infile.rename(intarget)
                bar.log('Moved to ' + print_name(intarget))
                ansfile = self.ans_path
                if ansfile.is_file():
                    anstarget = intarget.with_suffix('.ans')
                    ansfile.rename(anstarget)
                    bar.log('Moved to ' + print_name(anstarget))

            # Remove testcase if specified.
            elif validator_type == 'input' and config.args.remove:
                bar.log(Fore.RED + 'REMOVING TESTCASE!' + Style.RESET_ALL)
                if self.in_path.exists():
                    self.in_path.unlink()
                if self.ans_path.exists():
                    self.ans_path.unlink()

            break

        if success and not bad_testcase:
            if validator_type == 'input':
                validate.generic_validation(validator_type, self.in_path, bar=bar)

            if validator_type == 'answer':
                validate.generic_validation(validator_type, self.ans_path, bar=bar)

        return success


class Run:
    def __init__(self, problem, submission, testcase):
        self.problem = problem
        self.submission = submission
        self.testcase = testcase
        self.name = self.testcase.name
        self.result = None

        tmp_path = (
            self.problem.tmpdir / 'runs' / self.submission.short_path / self.testcase.short_path
        )
        self.out_path = tmp_path.with_suffix('.out')
        self.feedbackdir = tmp_path.with_suffix('.feedbackdir')
        self.feedbackdir.mkdir(exist_ok=True, parents=True)
        # Clean all files in feedbackdir.
        for f in self.feedbackdir.iterdir():
            if f.is_file():
                f.unlink()
            else:
                shutil.rmtree(f)

    # Return an ExecResult object amended with verdict.
    def run(self, *, interaction=None, submission_args=None):
        if self.problem.interactive:
            result = interactive.run_interactive_testcase(
                self, interaction=interaction, submission_args=submission_args
            )
        else:
            result = self.submission.run(self.testcase.in_path, self.out_path)
            if result.duration > self.problem.settings.timelimit:
                result.verdict = 'TIME_LIMIT_EXCEEDED'
                if result.timeout_expired:
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
                if result is False:
                    error(f'No output validators found for testcase {self.testcase.name}')
                    result = ExecResult(-1, 0, False, None, None)
                    result.verdict = 'VALIDATOR_CRASH'
                else:
                    result.duration = duration

                    if result.ok is True:
                        result.verdict = 'ACCEPTED'
                    elif result.ok is False:
                        result.verdict = 'WRONG_ANSWER'
                    else:
                        config.n_error += 1
                        result.verdict = 'VALIDATOR_CRASH'

            # Delete .out files larger than 1MB.
            if (
                not config.args.error
                and self.out_path.is_file()
                and self.out_path.stat().st_size > 1_000_000_000
            ):
                self.out_path.unlink()

        self.result = result
        return result

    def _validate_output(self):
        validator_type = 'output'
        output_validators = self.problem.validators(validator_type)
        if output_validators is False:
            return False

        last_result = False
        for output_validator in output_validators:
            flags = self.testcase.testdata_yaml_validator_flags(validator_type, output_validator)
            if flags is False:
                continue

            ret = output_validator.run(self.testcase, self, args=flags)

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

        # NOTE: Judging of interactive problems on systems without `os.wait4` is
        # suboptimal because we cannot determine which of the submission and
        # interactor exits first. Thus, we don't distinguish the different non-AC
        # verdicts.
        if self.problem.interactive and (is_windows() or is_bsd()):
            wrong_verdicts = ['WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR']
            for wrong_verdict in wrong_verdicts:
                if wrong_verdict in self.expected_verdicts:
                    self.expected_verdicts += wrong_verdicts
                    break

    def _get_expected_verdicts(self):
        verdicts = []

        # Look for '@EXPECTED_RESULTS@: ' in all source files. This should be followed by a comma separated list of the following:
        # - ACCEPTED / CORRECT
        # - WRONG_ANSWER / WRONG-ANSWER / NO-OUTPUT
        # - TIME_LIMIT_EXCEEDED / TIMELIMIT
        # - RUN_TIME_ERROR / RUN-ERROR
        domjudge_verdict_map = {
            'CORRECT': 'ACCEPTED',
            'WRONG-ANSWER': 'WRONG_ANSWER',
            'TIMELIMIT': 'TIME_LIMIT_EXCEEDED',
            'RUN-ERROR': 'RUN_TIME_ERROR',
            'NO-OUTPUT': 'WRONG_ANSWER',
            'CHECK-MANUALLY': None,
            'COMPILER-ERROR': None,
        }
        # Matching is case insensitive and all source files are checked.
        key = '@EXPECTED_RESULTS@: '
        if self.path.is_file():
            files = [self.path]
        elif self.path.is_dir():
            files = self.path.glob('**/*')
        else:
            files = []
        for f in files:
            if not f.is_file():
                continue
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
                        error(
                            f'@EXPECTED_RESULTS@: `{arg}` for submission {self.short_path} is not valid'
                        )
                        continue
                    verdicts.append(arg)
                break
            except (UnicodeDecodeError, ValueError):
                # Skip binary files.
                # Skip files where the key does not occur.
                pass

        if len(self.path.parts) >= 3 and self.path.parts[-3] == 'submissions':
            # Submissions in any of config.VERDICTS should not have `@EXPECTED_RESULTS@: `, and vice versa.
            # See https://github.com/DOMjudge/domjudge/issues/1861
            subdir = self.short_path.parts[0].upper()
            if subdir in config.VERDICTS:
                if len(verdicts) != 0:
                    warn(f'@EXPECTED_RESULTS@ in submission {self.short_path} is ignored.')
                verdicts = [subdir]
            else:
                if len(verdicts) == 0:
                    error(
                        f'Submission {self.short_path} must have @EXPECTED_RESULTS@. Defaulting to ACCEPTED.'
                    )

        if len(verdicts) == 0:
            verdicts = ['ACCEPTED']
        return verdicts

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

    # Run this submission on all testcases for the current problem.
    # Returns (OK verdict, printed newline)
    def run_all_testcases(
        self, max_submission_name_len=None, table_dict=None, *, needs_leading_newline
    ):
        runs = [Run(self.problem, self, testcase) for testcase in self.problem.testcases()]
        max_item_len = max(len(run.name) for run in runs) + max_submission_name_len - len(self.name)

        bar = ProgressBar(
            'Running ' + self.name,
            count=len(runs),
            max_len=max_item_len,
            needs_leading_newline=needs_leading_newline,
        )

        max_duration = -1

        verdict = (-100, 'ACCEPTED', 'ACCEPTED', 0)  # priority, verdict, print_verdict, duration
        verdict_run = None

        def process_run(run, p):
            nonlocal max_duration, verdict, verdict_run

            localbar = bar.start(run)
            result = run.run()

            if result.verdict == 'ACCEPTED':
                validate.generic_validation('output', run.out_path, bar=localbar)

            new_verdict = (
                config.PRIORITY[result.verdict],
                result.verdict,
                result.print_verdict(),
                result.duration,
            )
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

            # Add data from feedbackdir.
            for f in run.feedbackdir.iterdir():
                if not f.is_file():
                    localbar.warn(f'Validator wrote to {f} but it\'s not a file.')
                    continue
                try:
                    t = f.read_text()
                except UnicodeDecodeError:
                    localbar.warn(
                        f'Validator wrote to {f} but it cannot be parsed as unicode text.'
                    )
                    continue
                f.unlink()
                if not t:
                    continue
                if len(data) > 0 and data[-1] != '\n':
                    data += '\n'
                data += f'{f.name}:' + localbar._format_data(t) + '\n'

            localbar.done(got_expected, f'{result.duration:6.3f}s {result.print_verdict()}', data)

            # Lazy judging: stop on the first error when:
            # - not in verbose mode
            if config.args.verbose or config.args.table:
                return
            # - the result has max priority
            if result.verdict not in config.MAX_PRIORITY_VERDICT:
                return
            # - for TLE, the run was aborted because the global timeout expired
            if result.verdict == 'TIME_LIMIT_EXCEEDED' and not result.timeout_expired:
                return

            bar.count = None
            p.stop()

        p = parallel.Parallel(lambda run: process_run(run, p), pin=True)

        for run in runs:
            p.put(run)

        p.done()

        self.verdict = verdict[1]
        self.print_verdict = verdict[2]
        self.duration = max_duration

        # Use a bold summary line if things were printed before.
        if bar.logged:
            color = (
                Style.BRIGHT + Fore.GREEN
                if self.verdict in self.expected_verdicts
                else Style.BRIGHT + Fore.RED
            )
            boldcolor = Style.BRIGHT
        else:
            color = Fore.GREEN if self.verdict in self.expected_verdicts else Fore.RED
            boldcolor = ''

        printed_newline = bar.finalize(
            message=f'{max_duration:6.3f}s {color}{self.print_verdict:<20}{Style.RESET_ALL} @ {verdict_run.testcase.name}'
        )

        return (self.verdict in self.expected_verdicts, printed_newline)

    def test(self):
        print(ProgressBar.action('Running', str(self.name)), file=sys.stderr)

        testcases = self.problem.testcases(needans=False)

        if self.problem.interactive:
            output_validators = self.problem.validators('output')
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
                if result.duration > self.problem.settings.timeout:
                    status = f'{Fore.RED}Aborted!'
                    config.n_error += 1
                elif result.ok is not True and result.ok != -9:
                    config.n_error += 1
                    status = None
                    print(
                        f'{Fore.RED}Run time error!{Style.RESET_ALL} exit code {result.ok} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}',
                        file=sys.stderr,
                    )
                elif result.duration > self.problem.settings.timelimit:
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
                if result.verdict != 'ACCEPTED':
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
            output_validators = self.problem.validators('output')
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
            super().__init__(self.problem, self.path, skip_double_build_warning=True)
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
                if result.ok is not True:
                    config.n_error += 1
                    status = None
                    print(
                        f'{Fore.RED}Run time error!{Style.RESET_ALL} exit code {result.ok} {Style.BRIGHT}{result.duration:6.3f}s{Style.RESET_ALL}',
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
