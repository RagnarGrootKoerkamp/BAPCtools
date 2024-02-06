import program
import re
from util import *
from enum import Enum
from typing import Type


class Mode(Enum):
    """There are three validation modes for file validation"""

    INPUT = 1
    ANSWER = 2
    OUT_FILE = 3

    def __str__(self):
        return {
                Mode.INPUT: "input",
                Mode.ANSWER: "answer",
                Mode.OUT_FILE: "output file",
                }[self]



def _merge_constraints(constraints_path, constraints):
    # Merge with previous constraints.
    if constraints_path.is_file():
        for line in constraints_path.read_text().splitlines():
            loc, name, has_low, has_high, vmin, vmax, low, high = line.split()
            has_low = bool(int(has_low))
            has_high = bool(int(has_high))
            try:
                vmin = int(vmin)
            except ValueError:
                vmin = float(vmin)
            try:
                vmax = int(vmax)
            except ValueError:
                vmax = float(vmax)
            try:
                low = int(low)
            except ValueError:
                low = float(low)
            try:
                high = int(high)
            except ValueError:
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
    """Base class for AnswerValidator, InputValidator, and OutputValidator.

    They can all take constraints.


    Validators implement a run method that runs the validator. 

    It returns

    ExecResult: The result of running this validator on the given testcase.
        ExecResult.ok is True  if the this validator accepted.
        ExecResult.ok is False if that the this validator accepted.
    """

    FORMAT_VALIDATOR_LANGUAGES = ['checktestdata', 'viva']

    def __repr__(self):
        return type(self).__name__ + ': ' + str(self.path)

    def __init__(self, problem, path, skip_double_build_warning=False, check_constraints=False):
        program.Program.__init__(
            self, problem, path, skip_double_build_warning=skip_double_build_warning
        )

        if check_constraints:
            self.tmpdir = self.tmpdir.parent / (self.tmpdir.name + '_check_constraints')
        self.check_constraints = check_constraints

    def _run_helper(self, testcase, constraints, args):
        """Helper method for the run method in subclasses.
        Return:
            cwd: a current working directory for this testcase
            constraints_path: None or a path to the constraints file
            args: (possibly empty) list of arguments, possibly including --contraints_file
        """
        if testcase.in_path.is_relative_to(self.problem.tmpdir):
            cwd = testcase.in_path.with_suffix('.feedbackdir')
        else:
            cwd = self.problem.tmpdir / 'data' / testcase.short_path.with_suffix('.feedbackdir')
        cwd.mkdir(parents=True, exist_ok=True)
        arglist = []
        if args is not None:
            assert isinstance(args, list)
            arglist += args
        if constraints is not None:
            prefix = 'input' if isinstance(self, InputValidator) else 'answer'
            constraints_path = cwd / f'{prefix}_constraints_'
            if constraints_path.is_file():
                constraints_path.unlink()
            arglist += ['--constraints_file', constraints_path]
        else:
            constraints_path = None

        return cwd, constraints_path, arglist

    # .ctd, .viva, or otherwise called as: ./validator [arguments] < inputfile.
    # It may not read/write files.
    def _run_format_validator(self, testcase, cwd):
        assert self.language in Validator.FORMAT_VALIDATOR_LANGUAGES

        if isinstance(self, InputValidator):
            main_path = testcase.in_path
            bad = testcase.root == 'invalid_inputs'
        elif isinstance(self, AnswerValidator):
            main_path = testcase.ans_path
            bad = testcase.root == 'invalid_answers'
        else:
            assert False  # now also catches OutputValidator

        if self.language == 'checktestdata':
            with main_path.open() as main_file:
                return exec_command(
                    self.run_command, expect=0, stdin=main_file, cwd=cwd
                )

        if self.language == 'viva':
            # Called as `viva validator.viva testcase.in`.
            result = exec_command(
                self.run_command + [main_path.resolve()], expect=0, cwd=cwd
            )
            return result


class InputValidator(Validator):
    """
    Validate an input file (such as "testcase.in"), called as:

        ./validator [arguments] < input

    Also supports checktestdata and viva files, with different invocation.
    """

    def __str__(self):
        return "input"

    subdir = 'input_validators'
    source_dirs = ['input_validators', 'input_format_validators']

    def run(self, testcase, mode=Mode.INPUT, constraints=None, args=None) -> ExecResult:
        """
        Arguments
        ---------
        mode:
            must be Mode.INPUT
        """
        if mode != Mode.INPUT:
            raise ValueError("InputValidators only support Mode.INPUT")
        cwd, constraints_path, arglist = self._run_helper(testcase, constraints, args)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        invocation = self.run_command.copy()

        with testcase.in_path.open() as in_file:
            ret = exec_command(
                invocation + arglist,
                expect=config.RTV_AC,
                stdin=in_file,
                cwd=cwd,
                timeout=config.get_timeout(),
            )

        if constraints is not None:
            _merge_constraints(constraints_path, constraints)

        return ret


class AnswerValidator(Validator):
    """
    Validate the default answer file (such as "testcase.ans"), called as:

        ./validator input < answer.

    Also supports checktestdata and viva files, with different invocation.
    """

    def __str__(self):
        return "answer"

    subdir = 'answer_validators'
    source_dirs = ['answer_validators', 'answer_format_validators']

    def run(self, testcase, mode=Mode.ANSWER, constraints=None, args=None):
        """Return:
        ExecResult
        """

        if mode != Mode.ANSWER:
            raise ValueError("AnswerValidators only support Mode.ANSWER")

        cwd, constraints_path, arglist = self._run_helper(testcase, constraints, args)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        invocation = self.run_command + [testcase.in_path.resolve()]

        with testcase.ans_path.open() as ans_file:
            ret = exec_command(
                invocation + arglist,
                expect=config.RTV_AC,
                stdin=ans_file,
                cwd=cwd,
                timeout=config.get_timeout(),
            )

        if constraints is not None:
            _merge_constraints(constraints_path, constraints)

        return ret


class OutputValidator(Validator):
    """
    Validate the output of a submission

       ./validator input answer feedbackdir [arguments from problem.yaml] < output
    """

    def __str__(self):
        return "output"

    subdir = 'output_validators'

    source_dirs = ['output_validator', 'output_validators']

    def run(self, testcase, run=None, mode=None, constraints=None, args=None):
        """
        Run this validator on the given testcase.
        Arguments
        ---------
        run: Run | None
        If not None validate run.out_path

        Returns
        -------
        The ExecResult
        """

        if run is not None and mode is not None:
            raise ValueError(f"Exactly one of run and mode must be None")
        if run is not None:
            path = run.out_path
        else:
            match mode:
                case Mode.OUT_FILE:
                    if  testcase.out_path is None:
                        raise ValueError(f"Test case {testcase.name} has no .out file")
                    path = testcase.out_path.resolve()
                case Mode.ANSWER:
                    path = testcase.ans_path.resolve()
                case Mode.INPUT:
                    raise ValueError("OutputValidators do not support Mode.INPUT")

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            raise ValueError("Invalid output validator language")

        cwd, constraints_path, arglist = self._run_helper(testcase, constraints, args)

        feedbackdir = run.feedbackdir if run is not None else cwd
        invocation = (
            self.run_command
            + [testcase.in_path.resolve(), testcase.ans_path.resolve(), feedbackdir]
            + self.problem.settings.validator_flags
        )

        with path.open() as file:
            ret = exec_command(
                invocation + arglist,
                expect=config.RTV_AC,
                stdin=file,
                cwd=feedbackdir,
                timeout=config.get_timeout(),
            )

        if constraints is not None:
            _merge_constraints(constraints_path, constraints)

        return ret


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


def sanity_check(path, bar, strict_whitespace=True):
    """
    Does some generic checks on input, answer, or output files of a testcase, including

    - no unreadable characters
    - not too large

    if any of this is violated a warning is printed.
    use --no-testcase-sanity-checks to skip this

    args:
        strict_whitespace: Also check
        - no weird consecutive whitespaces ('  ', '\n ', ' \n')
        - no other_whitespaces (like '\t')
        - no whitespace at start of file
        - ensures newline at end of file

    """
    if config.args.no_testcase_sanity_checks:
        return

    if not path.exists():
        fatal(f"{path} not found during sanity check")
        return
    with open(path, 'rb') as file:
        name = {
            '.in': "Input",
            '.ans': "Answer",
            '.out': "Output",
        }[path.suffix]
        file_bytes = file.read()
        if _has_invalid_byte(file_bytes, other_whitespaces=not strict_whitespace):
            bar.warn(f'{name} contains unexpected characters but was accepted!')
        elif len(file_bytes) == 0:
            bar.warn(f'{name} is empty but was accepted!')
        elif len(file_bytes) > 20_000_000:
            bar.warn(f'{name} is larger than 20Mb!')
        elif strict_whitespace:
            if file_bytes[0] in [ord(' '), ord('\n')]:
                bar.warn(f'{name} starts with whitespace but was accepted!')
            elif file_bytes[-1] != ord('\n'):
                bar.warn(f'{name} does not end with a newline but was accepted!')
            elif _has_consecutive_whitespaces(file_bytes):
                bar.warn(f'{name} contains consecutive whitespace characters but was accepted!')
