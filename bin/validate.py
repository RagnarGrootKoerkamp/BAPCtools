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

def _merge_constraints(constraints_path, constraints):
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

# .ctd, .viva, or otherwise called as: ./validator [arguments] < inputfile.
# It may not read/write files.
class InputValidator(Validator):
    subdir = 'input_validators'

    # 'constraints': An optional dictionary mapping file locations to extremal values seen so far.
    # Return ExecResult
    def run(self, testcase, constraints=None):
        cwd = self.problem.tmpdir / 'data' / testcase.short_path.with_suffix('.feedbackdir')
        cwd.mkdir(parents=True, exist_ok=True)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        run_command = self.run_command + ['case_sensitive', 'space_change_sensitive']

        if constraints:
            constraints_path = cwd / 'constraints_'
            if constraints_path.is_file(): constraints_path.unlink()
            run_command += ['--constraints_file', constraints_path]

        with testcase.in_path.open() as in_file:
            ret = exec_command_2(
                run_command,
                expect=config.RTV_WA if testcase.bad_input else config.RTV_AC,
                stdin=in_file,
                cwd=cwd)

        if constraints: _merge_constraints(constraints_path, constraints)

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
    def run(self, testcase, run=None, constraints=None):
        if run is None:
            # When used as a format validator, act like an InputValidator.
            cwd = self.problem.tmpdir / 'data' / testcase.short_path.with_suffix('.feedbackdir')
            cwd.mkdir(parents=True, exist_ok=True)

            if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
                return Validator._run_format_validator(self, testcase, cwd)

            run_command = self.run_command+ [testcase.in_path, testcase.ans_path, cwd, 'case_sensitive', 'space_change_sensitive']

            if constraints:
                constraints_path = cwd / 'constraints_'
                if constraints_path.is_file(): constraints_path.unlink()
                run_command += ['--constraints_file', constraints_path]

            with testcase.ans_path.open() as ans_file:
                ret = exec_command_2(
                    run_command,
                    expect=config.RTV_WA if testcase.bad_output else config.RTV_AC,
                    stdin=ans_file,
                    cwd=cwd)

            if constraints: _merge_constraints(constraints_path, constraints)

            return ret

        assert constraints is None

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return False

        with run.out_path.open() as out_file:
            return exec_command_2(
                self.run_command + [testcase.in_path, testcase.ans_path, run.feedbackdir] + self.problem.settings.validator_flags,
                expect=config.RTV_AC,
                stdin=out_file,
                cwd=run.feedbackdir)

