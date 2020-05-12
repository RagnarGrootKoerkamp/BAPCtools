import program
import re
from util import *

import re

# TODO: Revamp this to new OO style.

def _quick_diff(ans, out):
    if ans.count('\n') <= 1 and out.count('\n') <= 1:
        return crop_output('Got ' + strip_newline(out) + ' wanted ' + strip_newline(ans))
    else:
        return ''


# return: (success, err, out=None)
def default_output_validator(ansfile, outfile, settings):
    # settings: floatabs, floatrel, case_sensitive, space_change_sensitive
    with open(ansfile, 'r') as f:
        indata1 = f.read()

    with open(outfile, 'r') as f:
        indata2 = f.read()

    if indata1 == indata2:
        return (True, '', None)

    if not settings.case_sensitive:
        # convert to lowercase...
        data1 = indata1.lower()
        data2 = indata2.lower()

        if data1 == data2:
            return (True, 'case', None)
    else:
        data1 = indata1
        data2 = indata2

    if settings.space_change_sensitive and settings.floatabs == None and settings.floatrel == None:
        return (False, _quick_diff(data1, data2), None)

    if settings.space_change_sensitive:
        words1 = re.split(r'\b(\S+)\b', data1)
        words2 = re.split(r'\b(\S+)\b', data2)
    else:
        words1 = re.split(r'[ \n]+', data1)
        words2 = re.split(r'[ \n]+', data2)
        if len(words1) > 0 and words1[-1] == '':
            words1.pop()
        if len(words2) > 0 and words2[-1] == '':
            words2.pop()
        if len(words1) > 0 and words1[0] == '':
            words1.pop(0)
        if len(words2) > 0 and words2[0] == '':
            words2.pop(0)

    if words1 == words2:
        if not settings.space_change_sensitive:
            return (True, 'white space', None)
        else:
            print('Strings became equal after space sensitive splitting! Something is wrong!')
            exit()

    if settings.floatabs is None and settings.floatrel is None:
        return (False, _quick_diff(data1, data2), None)

    if len(words1) != len(words2):
        return (False, _quick_diff(data1, data2), None)

    peakabserr = 0
    peakrelerr = 0
    for (w1, w2) in zip(words1, words2):
        if w1 != w2:
            try:
                f1 = float(w1)
                f2 = float(w2)
                abserr = abs(f1 - f2)
                relerr = abs(f1 - f2) / f1 if f1 != 0 else 1000
                peakabserr = max(peakabserr, abserr)
                peakrelerr = max(peakrelerr, relerr)
                if ((settings.floatabs is None or abserr > settings.floatabs)
                        and (settings.floatrel is None or relerr > settings.floatrel)):
                    return (False, _quick_diff(data1, data2), None)
            except ValueError:
                return (False, _quick_diff(data1, data2), None)

    return (True, 'float: abs {0:.2g} rel {1:.2g}'.format(peakabserr, peakrelerr), None)


# call output validators as ./validator in ans feedbackdir additional_arguments < out
# return (success, err, out) for the last validator that was run.
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
        header = output_validator[0] + ': ' if len(output_validators) > 1 else ''
        with open(outfile, 'r') as outf:
            judgepath = config.tmpdir / 'judge'
            judgepath.mkdir(parents=True, exist_ok=True)
            judgemessage = judgepath / 'judgemessage.txt'
            judgeerror = judgepath / 'judgeerror.txt'
            val_ok, err, out = exec_command(
                output_validator[1] +
                [testcase.in_path,
                 testcase.ans_path, judgepath] + flags,
                expect=config.RTV_AC,
                stdin=outf)
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
        # simple `program < test.in` for input validation and ctd output validation
        if Path(validator[0]).suffix == '.ctd':
            ok, err, out = exec_command(
                validator[1],
                # TODO: Can we make this more generic? CTD returning 0 instead of 42
                # is a bit annoying.
                expect=1 if bad_testcase else 0,
                stdin=main_file.open())

        elif Path(validator[0]).suffix == '.viva':
            # Called as `viva validator.viva testcase.in`.
            ok, err, out = exec_command(
                validator[1] + [main_file],
                # TODO: Can we make this more generic? VIVA returning 0 instead of 42
                # is a bit annoying.
                expect=1 if bad_testcase else 0)
            # Slightly hacky: CTD prints testcase errors on stderr while VIVA prints
            # them on stdout.
            err = out

        elif validator_type == 'input':
            constraints_file = config.tmpdir / 'constraints'
            if constraints_file.is_file():
                constraints_file.unlink()

            ok, err, out = exec_command(
                # TODO: Store constraints per problem.
                validator[1] +
                (['--constraints_file', constraints_file] if check_constraints else []),
                expect=config.RTV_WA if bad_testcase else config.RTV_AC,
                stdin=main_file.open())

            # Merge with previous constraints.
            if constraints_file.is_file():
                for line in constraints_file.read_text().splitlines():
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

                constraints_file.unlink()

        else:
            # more general `program test.in test.ans feedbackdir < test.in/ans` output validation otherwise
            ok, err, out = exec_command(
                validator[1] +
                [testcase.in_path, testcase.ans_path, config.tmpdir] +
                ['case_sensitive', 'space_change_sensitive'],
                expect=config.RTV_WA if bad_testcase else config.RTV_AC,
                stdin=main_file.open())

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
