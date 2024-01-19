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
            bad = testcase.bad_input
        elif isinstance(self, OutputValidator):
            main_path = testcase.ans_path
            bad = testcase.bad_output
        else:
            assert False

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


# .ctd, .viva, or otherwise called as: ./validator [arguments] < inputfile.
# It may not read/write files.
class InputValidator(Validator):
    subdir = 'input_validators'

    # 'constraints': An optional dictionary mapping file locations to extremal values seen so far.
    # `args`: Optional list of additional arguments to pass. Used from testdata.yaml configuration.
    # Return ExecResult
    def run(self, testcase, constraints=None, args=None):
        if testcase.in_path.is_relative_to(self.problem.tmpdir):
            cwd = testcase.in_path.with_suffix('.feedbackdir')
        else:
            cwd = self.problem.tmpdir / 'data' / testcase.short_path.with_suffix('.feedbackdir')
        cwd.mkdir(parents=True, exist_ok=True)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        run_command = self.run_command.copy()

        if args is not None:
            assert isinstance(args, list)
            run_command += args

        if constraints is not None:
            constraints_path = cwd / 'input_constraints_'
            if constraints_path.is_file():
                constraints_path.unlink()
            run_command += ['--constraints_file', constraints_path]

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
    def run(self, testcase, run=None, constraints=None, args=None):
        if run is None:
            # When used as a format validator, act like an InputValidator.
            if testcase.in_path.is_relative_to(self.problem.tmpdir):
                cwd = testcase.in_path.with_suffix('.feedbackdir')
            else:
                cwd = self.problem.tmpdir / 'data' / testcase.short_path.with_suffix('.feedbackdir')
            cwd.mkdir(parents=True, exist_ok=True)

            if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
                return Validator._run_format_validator(self, testcase, cwd)

            run_command = self.run_command + [
                testcase.in_path.resolve(),
                testcase.ans_path.resolve(),
                cwd,
                'case_sensitive',
                'space_change_sensitive',
            ]

            if args is not None:
                assert isinstance(args, list)
                run_command += args

            if constraints is not None:
                constraints_path = cwd / 'output_constraints_'
                if constraints_path.is_file():
                    constraints_path.unlink()
                run_command += ['--constraints_file', constraints_path]

            with testcase.ans_path.open() as ans_file:
                ret = exec_command(
                    run_command,
                    expect=config.RTV_AC,
                    stdin=ans_file,
                    cwd=cwd,
                    timeout=config.get_timeout(),
                )
                # For bad outputs, 'invert' the return code: any non-AC exit code is fine, while AC is not fine.
                if testcase.bad_output:
                    ret.ok = True if ret.ok is not True else config.RTV_AC

            if constraints is not None:
                _merge_constraints(constraints_path, constraints)

            return ret

        assert constraints is None

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return False

        with run.out_path.open() as out_file:
            return exec_command(
                self.run_command
                + [testcase.in_path.resolve(), testcase.ans_path.resolve(), run.feedbackdir]
                + self.problem.settings.validator_flags
                + (args if args else []),
                expect=config.RTV_AC,
                stdin=out_file,
                cwd=run.feedbackdir,
                timeout=config.get_timeout(),
            )


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
    assert validator_type in ['input_format', 'output_format', 'output']
    if config.args.no_testcase_sanity_checks:
        return

    # Todo we could check for more stuff that is likely an error like `.*-0.*`
    if validator_type == 'input_format':
        name = 'Testcase'
        strict = True
    elif validator_type == 'output_format':
        name = 'Expected answer'
        strict = True
    elif validator_type == 'output':
        name = 'Answer'
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
