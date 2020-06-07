import program
import re
from util import *

class Validator(program.Program):

    # NOTE: This only works for checktestdata and Viva validators.
    FORMAT_VALIDATOR_LANGUAGES = ['checktestdata', 'viva']

    # Return ExecResult
    def _run_format_validator(self, testcase, cwd):
        assert self.language in Validator.FORMAT_VALIDATOR_LANGUAGES

        if isinstance(self, InputValidator):
            main_path = testcase.in_path
        elif isinstance(self, OutputValidator):
            main_path = testcase.ans_path
        else: assert False

        if self.language == 'checktestdata':
            with main_path.open() as main_file:
                return exec_command_2(
                    self.run_command,
                    expect=1 if testcase.bad else 0,
                    stdin=main_file,
                    cwd=cwd)

        if self.language == 'viva':
            # Called as `viva validator.viva testcase.in`.
            result = exec_command_2(
                self.run_command + [main_path],
                expect=1 if testcase.bad else 0,
                cwd=cwd)
            # Slightly hacky: CTD prints testcase errors on stderr while VIVA prints
            # them on stdout.
            result.err = out
            result.out = None
            return result


# .ctd, .viva, or otherwise called as: ./validator [arguments] < inputfile.
# It may not read/write files.
class InputValidator(Validator):
    subdir = 'input_validators'

    # 'constraints': An optional dictionary mapping file locations to extremal values seen so far.
    # Return ExecResult
    def run(self, testcase, constraints=None):
        # NOTE: We reuse the generator directory. Since the input validator isn't supposed to read/write anyway, that's fine.
        cwd = self.problem.tmpdir / 'data' / testcase.short_path
        cwd.mkdir(parents=True, exist_ok=True)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        run_command = self.run_command + ['case_sensitive', 'space_change_sensitive']

        if constraints:
            constraints_path = cwd / 'constraints_'
            if constraints_path.is_file(): constraints_path.unlink()
            run_command += ['--constraints_file', constraints_path]

        with testcase.in_path.open() as in_file:
            return = exec_command_2(
                run_command,
                expect=config.RTV_WA if testcase.bad else config.RTV_AC,
                stdin=in_file,
                cwd=cwd)

        if constraints:
            self.merge_constraints(constraints_path, constraints)

    @static_method
    def merge_constraints(constraints_path, constraints):
        # Merge with previous constraints.
        if constraints_path.is_file():
            for line in constraints_path.read_text().splitlines():
                loc, has_low, has_high, vmin, vmax, low, high = line.split()
                has_low = bool(int(has_low))
                has_high = bool(int(has_high))
                try:
                    vmin = int(vmin)
                except:
                    vmin = float(vmin)
                try:
                    vmax = int(vmax)
                except:
                    vmax = float(vmax)
                if loc in constraints:
                    c = constraints[loc]
                    has_low |= c[0]
                    has_high |= c[1]
                    if c[2] < vmin:
                        vmin = c[2]
                        low = c[4]
                    if c[3] > vmax:
                        vmax = c[3]
                        high = c[5]
                constraints[loc] = (has_low, has_high, vmin, vmax, low, high)

            constraints_path.unlink()


# OutputValidators can run in two modes:
# Team output validation:
#       called as: ./validator input answer feedbackdir [arguments from problem.yaml] < output.
# Testcase validation:
#       called as: ./validator input answer feedbackdir case_sensitive space_change_sensitive < answer.
#       This mode also supports checktestdata and viva files.
class OutputValidator(Validator):
    subdir = 'output_validators'

    # When run is None, validate the testcase. Otherwise, validate the output of the given run.
    # Return ExecResult
    def run(self, testcase, run=None):
        if run is None:
            assert tmpdir is None
            cwd = self.problem.tmpdir / 'data' / testcase.short_path.with_suffix('.feedbackdir')
            cwd.mkdir(parents=True, exist_ok=True)

            if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
                return Validator._run_format_validator(self, testcase, cwd)

            with testcase.in_path.open() as in_file:
                return exec_command_2(
                    self.run_command + [testcase.in_path, testcase.ans_path, cwd, 'case_sensitive', 'space_change_sensitive'],
                    expect=config.RTV_WA if testcase.bad else config.RTV_AC,
                    stdin=in_file,
                    cwd=cwd)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return False



        with run.out_path.open() as out_file:
            return exec_command_2(
                self.run_command + [testcase.in_path, testcase.ans_path, run.feedbackdir] + self.problem.settings.validator_flags,
                expect=config.RTV_AC,
                stdin=out_file,
                cwd=run.feedbackdir)




# TODO: Revamp this to new OO style.

# call output validators as ./validator in ans feedbackdir additional_arguments < out
# return (success, err, out) for the last validator that was run.
# Move to RUN
def custom_output_validator(testcase, outfile, settings, output_validators):
    flags = []
    if settings.space_change_sensitive:
        flags += ['space_change_sensitive']
    if settings.case_sensitive:
        flags += ['case_sensitive']

    run_all_validators = hasattr(settings, 'all_validators') and settings.all_validators

    ok = None
    err = None
    out = None
    for output_validator in output_validators:
        # TODO: MOVE TO VALIDATOR PROGRAM
        header = output_validator[0] + ': ' if len(output_validators) > 1 else ''
        # TODO: Call OutputValidator.run()
        judgemessage = judgepath / 'judgemessage.txt'
        judgeerror = judgepath / 'judgeerror.txt'
        if err is None:
            err = ''
        if judgemessage.is_file():
            err += judgemessage.read_text()
            judgemessage.unlink()
        if judgeerror.is_file():
            # Remove any std output because it will usually only contain the
            err = judgeerror.read_text()
            judgeerror.unlink()
        if err:
            err = header + err

        if ok == None:
            ok = val_ok
        if run_all_validators and val_ok != ok:
            ok = 'INCONSISTENT_VALIDATORS'
            err = 'INCONSISTENT VALIDATORS: ' + err
            return (ok, err, out)

        if val_ok is True:
            continue
        if not run_all_validators:
            break

    if ok == config.RTV_WA:
        ok = False
    return (ok, err, out)


# TODO: Move to TESTCASE.validate()
def validate_testcase(problem,
                      testcase,
                      validators,
                      validator_type,
                      *,
                      bar,
                      check_constraints=False,
                      constraints=None):
    ext = '.in' if validator_type == 'input' else '.ans'

    bad_testcase = False
    if validator_type == 'input':
        bad_testcase = 'data/bad/' in str(testcase.in_path) and not testcase.ans_path.is_file() and not testcase.with_suffix('.out').is_file()

    if validator_type == 'output':
        bad_testcase = 'data/bad/' in str(testcase.in_path)

    main_file = testcase.with_suffix(ext)
    if bad_testcase and validator_type == 'output' and main_file.with_suffix('.out').is_file():
        main_file = testcase.with_suffix('.out')

    success = True

    for validator in validators:
        if True:
            pass
        # TODO Call Validator.run()
        else:

        ok = ok is True
        success &= ok
        message = ''

        # Failure?
        if ok:
            message = 'PASSED ' + validator[0]
        else:
            message = 'FAILED ' + validator[0]

        # Print stdout and stderr whenever something is printed
        if not err: err = ''
        if out and config.args.error:
            out = f'\n{cc.red}VALIDATOR STDOUT{cc.reset}\n' + cc.orange + out
        else:
            out = ''

        bar.part_done(ok, message, data=err + out)

        if not ok:
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


# Validate the .in and .ans files for a problem.
# For input:
# - build+run or all files in input_validators
#
# For output:
# - 'default' validation:
#   build+run or all files in output_validators
# - 'custom'  validation:
#   none, .ans file not needed.
#
# We always pass both the case_sensitive and space_change_sensitive flags.
def validate(problem, validator_type, settings, check_constraints=False):
    assert validator_type in ['input', 'output']

    if check_constraints:
        if not config.args.cpp_flags:
            config.args.cpp_flags = ''
        config.args.cpp_flags += ' -Duse_source_location'

        validators = get_validators(problem, validator_type, check_constraints=True)
    else:
        validators = get_validators(problem, validator_type)

    if settings.validation == 'custom interactive' and validator_type == 'output':
        log('Not validating .ans for interactive problem.')
        return True

    if len(validators) == 0:
        error(f'No {validator_type} validators found!')
        return False

    testcases = problem.testcases(needans=validator_type == 'output')

    # Get the bad testcases:
    # For input validation, look for .in files without .ans or .out.
    # For output validator, look for .in files with a .ans or .out.
    for f in glob(problem, 'data/bad/**/*.in'):
        has_ans = f.with_suffix('.ans').is_file()
        has_out = f.with_suffix('.out').is_file()
        if validator_type == 'input':
            # This will only be marked 'bad' if there is no .ans or .out.
            testcases.append(f)
        if validator_type == 'output' and (has_ans or has_out):
            testcases.append(f)

    if len(testcases) == 0:
        return True

    ext = '.in' if validator_type == 'input' else '.ans'
    action = 'Validating ' + validator_type

    success = True

    constraints = {}

    # validate the testcases
    bar = ProgressBar(action, items=[t.name for t in testcases])
    for testcase in testcases:
        bar.start(print_name(testcase.with_suffix(ext)))
        success &= validate_testcase(problem,
                                     testcase,
                                     validators,
                                     validator_type,
                                     bar=bar,
                                     check_constraints=check_constraints,
                                     constraints=constraints)
        bar.done()

    # Make sure all constraints are satisfied.
    for loc, value in sorted(constraints.items()):
        loc = Path(loc).name
        has_low, has_high, vmin, vmax, low, high = value
        if not has_low:
            warn(
                f'BOUND NOT REACHED: The value at {loc} was never equal to the lower bound of {low}. Min value found: {vmin}'
            )
        if not has_high:
            warn(
                f'BOUND NOT REACHED: The value at {loc} was never equal to the upper bound of {high}. Max value found: {vmax}'
            )
        success = False

    if not config.verbose and success:
        print(ProgressBar.action(action, f'{cc.green}Done{cc.reset}'))
        if validator_type == 'output':
            print()
    else:
        print()

    return success
