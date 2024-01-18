import program
import re
from util import *


def _merge_constraints(constraints_path, constraints):
    # Merge with previous constraints.
    if constraints_path.is_file():
        for line in constraints_path.read_text().splitlines():
            loc, name, has_low, has_high, vmin, vmax, low, high = line.split()
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
            try:
                low = int(low)
            except:
                low = float(low)
            try:
                high = int(high)
            except:
                high = float(high)
            if loc in constraints:
                c = constraints[loc]
                has_low |= c[1]
                has_high |= c[2]
                if c[3] < vmin:
                    vmin = c[3]
                if c[4] > vmax:
                    vmax = c[4]
                if c[5] > low:
                    low = c[5]
                if c[6] < high:
                    high = c[6]
            constraints[loc] = (name, has_low, has_high, vmin, vmax, low, high)

        constraints_path.unlink()

class Validator(program.Program):
    """ Base class for AnswerValidator, InputValidator, and Validator.

    They can all take constraints.
    Answer and input validators may use bespoke invocations for .ctd and Viva files.
    """

    FORMAT_VALIDATOR_LANGUAGES = ['checktestdata', 'viva']

    def __repr__(self):
        return type(self).__name__ + ': ' + str(self.path)

    def __init__(self, problem, path, skip_double_build_warning=False, check_constraints=False):
        program.Program.__init__(self, problem, path, skip_double_build_warning=skip_double_build_warning)

        if check_constraints:
            self.tmpdir = self.tmpdir.parent / (self.tmpdir.name + '_check_constraints')
        self.check_constraints = check_constraints

    def setup(self, command, testcase, constraints, args):
        """ Prepare invocation command, current working directory, and (if needed) constraints 
        path for the current testcase
        """

        if testcase.in_path.is_relative_to(self.problem.tmpdir):
            cwd = testcase.in_path.with_suffix('.feedbackdir')
        else:
            cwd = self.problem.tmpdir / 'data' / testcase.short_path.with_suffix('.feedbackdir')
        cwd.mkdir(parents=True, exist_ok=True)

        assembled_command = command.copy()

        if args is not None:
            assert isinstance(args, list)
            assembled_command += args

        if constraints is not None:
            validator_type = 'input' if isinstance(self, InputValidator) else 'answer'
            constraints_path = cwd / f'{validator_type}_constraints_'
            if constraints_path.is_file():
                constraints_path.unlink()
            assembled_command += ['--constraints_file', constraints_path]
        else:
            constraints_path = None

        return assembled_command, cwd, constraints_path


    # .ctd, .viva, or otherwise called as: ./validator [arguments] < inputfile.
    # It may not read/write files.
    def _run_format_validator(self, testcase, cwd):
        assert self.language in Validator.FORMAT_VALIDATOR_LANGUAGES

        if isinstance(self, InputValidator):
            main_path = testcase.in_path
            bad = testcase.bad_input
        elif isinstance(self, AnswerValidator):
            main_path = testcase.ans_path
            bad = testcase.bad_output
        else:
            assert False # now also catches OutputValidator

        if self.language == 'checktestdata':
            with main_path.open() as main_file:
                return exec_command(
                    self.run_command, expect=1 if bad else 0, stdin=main_file, cwd=cwd
                )

        if self.language == 'viva':
            # Called as `viva validator.viva testcase.in`.
            result = exec_command(
                self.run_command + [main_path.resolve()], expect=1 if bad else 0, cwd=cwd
            )
            return result


class InputValidator(Validator):
    subdir = 'input_validators'

    def run(self, testcase, constraints=None, args=None):
        run_command, cwd, constraints_path = self.setup(self.run_command.copy(), testcase, constraints, args)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        with testcase.in_path.open() as in_file:
            ret = exec_command(
                run_command,
                expect=config.RTV_AC,
                stdin=in_file,
                cwd=cwd,
                timeout=config.get_timeout(),
            )
            # For bad inputs, 'invert' the return code: any non-AC exit code is fine, while AC is not fine.
            if testcase.bad_input:
                ret.ok = True if ret.ok is not True else config.RTV_AC

        if constraints is not None:
            _merge_constraints(constraints_path, constraints)

        return ret


class AnswerValidator(Validator):
    # Validate the default answer file (such as "testcase.ans"),
    # typically just a syntax check
    #
    # called as: ./validator input < answer.
    # This mode also supports checktestdata and viva files.

    subdir = 'answer_validators'

    def run(self, testcase, constraints=None, args=None):

        if args:
            error("Answer validator {self} called with args; not supported")
        run_command, cwd, constraints_path = self.setup(
                self.run_command.copy() + [testcase.in_path.resolve()],
                testcase,
                constraints,
                None) # should supply args here

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        with testcase.ans_path.open() as ans_file:
            ret = exec_command(
                run_command,
                expect=config.RTV_AC,
                stdin=ans_file,
                cwd=cwd,
                timeout=config.get_timeout(),
            )

        if constraints is not None:
            _merge_constraints(constraints_path, constraints)

        return ret

class OutputValidator(Validator):
    # Team output validation:
    #       called as: ./validator input answer feedbackdir [arguments from problem.yaml] < output.
    subdir = 'output_validators'

    # Validate the output of the given run.
    # Return ExecResult
    def run(self, testcase, run=None, constraints=None, args=None):

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            assert False # this should never happen
    
        run_command, _, constraints_path = self.setup(
                self.run_command + [
                    testcase.in_path.resolve(),
                    testcase.ans_path.resolve(),
                    run.feedbackdir
                    ] + self.problem.settings.validator_flags,
                testcase,
                constraints,
                args)

        with run.out_path.open() as out_file:
            return exec_command(
                run_command,
                expect=config.RTV_AC,
                stdin=out_file,
                cwd=run.feedbackdir,
                timeout=config.get_timeout(),
            )

        if constraints is not None:
            _merge_constraints(constraints_path, constraints)


# Checks if byte is printable or whitespace
def _in_invalid_byte(byte, *, other_whitespaces=False):
    if other_whitespaces:
        if byte == ord('\t'):
            return False
        if byte == ord('\r'):
            return False
        if byte == ord('\v'):
            return False
        if byte == ord('\f'):
            return False
    if byte == ord('\n'):
        return False
    if byte >= 0x20 and byte < 0x7F:
        return False
    return True


def _has_invalid_byte(bytes, *, other_whitespaces=False):
    return any(_in_invalid_byte(b, other_whitespaces=other_whitespaces) for b in bytes)


# assumes that the only possible whitespaces are space and newline
# allows \n\n
def _has_consecutive_whitespaces(bytes):
    last = -1
    for byte in bytes:
        cur_whitespace = byte == ord(' ') or byte == ord('\n')
        if last == ord(' ') and cur_whitespace:
            return True
        if last == ord('\n') and byte == ord(' '):
            return True
        last = byte
    return False


# Does some generic checks on input/output:
# - no unreadable characters
# - no weird consecutive whitespaces ('  ', '\n ', ' \n')
# - no whitespace at start of file
# - ensures newline at end of file
# - not too large
# if any of this is violated a warning is printed
# use --no-testcase-sanity-checks to skip this
def generic_validation(validator_type, file, *, bar):
    assert validator_type in ['input', 'answer', 'output']
    if config.args.no_testcase_sanity_checks:
        return

    # Todo we could check for more stuff that is likely an error like `.*-0.*`
    if validator_type == 'input':
        name = 'Testcase'
        strict = True
    elif validator_type == 'answer':
        name = 'Default answer'
        strict = True
    elif validator_type == 'output':
        name = 'Output'
        strict = False

    if file.exists():
        bytes = file.read_bytes()
        if _has_invalid_byte(bytes, other_whitespaces=not strict):
            bar.warn(f'{name} contains unexpected characters but was accepted!')
        elif len(bytes) == 0:
            bar.warn(f'{name} is empty but was accepted!')
        elif len(bytes) > 20_000_000:
            bar.warn(f'{name} is larger than 20Mb!')
        elif strict:
            if bytes[0] == ord(' ') or bytes[0] == ord('\n'):
                bar.warn(f'{name} starts with whitespace but was accepted!')
            elif bytes[-1] != ord('\n'):
                bar.warn(f'{name} does not end with a newline but was accepted!')
            elif _has_consecutive_whitespaces(bytes):
                bar.warn(f'{name} contains consecutive whitespace characters but was accepted!')
