import re
from util import *
from enum import Enum
from collections.abc import Sequence
from typing import Final

import program
import testcase


class Mode(Enum):
    """There are four validation modes for file validation"""

    INPUT = 1
    ANSWER = 2
    INVALID = 3
    VALID_OUTPUT = 4

    def __str__(self):
        return {
            Mode.INPUT: "input",
            Mode.ANSWER: "answer",
            Mode.INVALID: "invalid files",
            Mode.VALID_OUTPUT: "valid output",
        }[self]


# loc -> (name, has_low, has_high, vmin, vmax, low, high)
ConstraintsDict = dict[
    str, tuple[str, bool, bool, int | float, int | float, int | float, int | float]
]


def _to_number(s: str) -> int | float:
    try:
        return int(s)
    except ValueError:
        return float(s)


def _merge_constraints(constraints_path: Path, constraints: ConstraintsDict):
    # Merge with previous constraints.
    if constraints_path.is_file():
        for line in constraints_path.read_text().splitlines():
            loc, *rest = line.split()
            assert len(rest) == 7
            name = rest[0]
            has_low = bool(int(rest[1]))
            has_high = bool(int(rest[2]))
            vmin = _to_number(rest[3])
            vmax = _to_number(rest[4])
            low = _to_number(rest[5])
            high = _to_number(rest[6])
            if loc in constraints:
                c = constraints[loc]
                has_low |= c[1]
                has_high |= c[2]
                if c[3] < vmin:
                    vmin = c[3]
                if c[4] > vmax:
                    vmax = c[4]
                if c[5] < low:
                    low = c[5]
                if c[6] > high:
                    high = c[6]
            constraints[loc] = (name, has_low, has_high, vmin, vmax, low, high)

        constraints_path.unlink()


class Validator(program.Program):
    """Base class for AnswerValidator, InputValidator, and OutputValidator.

    They can all take constraints.


    Validators implement a run method that runs the validator.

    It returns

    ExecResult: The result of running this validator on the given testcase.
        ExecResult.status == ExecStatus.ACCEPTED  if the validator accepted.
        ExecResult.status == ExecStatus.REJECTED if the validator rejected.
    """

    FORMAT_VALIDATOR_LANGUAGES: Final[Sequence[str]] = ["checktestdata", "viva"]

    def __repr__(self):
        return type(self).__name__ + ": " + str(self.path)

    def __init__(
        self,
        problem,
        path,
        subdir,
        skip_double_build_warning=False,
        check_constraints=False,
    ):
        super().__init__(
            problem,
            path,
            subdir,
            limits={
                "timeout": problem.limits.validation_time,
                "memory": problem.limits.validation_memory,
            },
            skip_double_build_warning=skip_double_build_warning,
        )
        assert self.__class__ is not Validator  # Validator is abstract and may not be instantiated

        if check_constraints:
            self.tmpdir: Path = self.tmpdir.parent / (self.tmpdir.name + "_check_constraints")
        self.check_constraints = check_constraints

    def _run_helper(self, testcase, constraints, args):
        """Helper method for the run method in subclasses.
        Return:
            cwd: a current working directory for this testcase
            constraints_path: None or a path to the constraints file
            args: (possibly empty) list of arguments, possibly including --contraints_file
        """
        if testcase.in_path.is_relative_to(self.problem.tmpdir):
            cwd = testcase.in_path.with_suffix(".feedbackdir")
        else:
            name = self.tmpdir.relative_to(self.problem.tmpdir)
            cwd = (
                self.problem.tmpdir
                / "tool_runs"
                / name
                / testcase.short_path.with_suffix(".feedbackdir")
            )
        cwd.mkdir(parents=True, exist_ok=True)
        arglist = []
        if args is not None:
            assert isinstance(args, list)
            arglist += args
        if constraints is not None:
            prefix = "input" if isinstance(self, InputValidator) else "answer"
            constraints_path = cwd / f"{prefix}_constraints_"
            if constraints_path.is_file():
                constraints_path.unlink()
            arglist += ["--constraints_file", constraints_path]
        else:
            constraints_path = None

        return cwd, constraints_path, arglist

    # .ctd, .viva, or otherwise called as: ./validator [arguments] < inputfile.
    # It may not read/write files.
    def _run_format_validator(self, testcase, cwd):
        assert self.language in Validator.FORMAT_VALIDATOR_LANGUAGES
        assert self.run_command is not None, "Validator should be built before running it"

        if isinstance(self, InputValidator):
            main_path = testcase.in_path
        elif isinstance(self, AnswerValidator):
            main_path = testcase.ans_path
        else:
            assert False  # now also catches OutputValidator

        def format_exec_code_map(returncode):
            if returncode == 0:
                return ExecStatus.ACCEPTED
            if returncode == 1:
                return ExecStatus.REJECTED
            if returncode == -9:
                return ExecStatus.TIMEOUT
            return ExecStatus.ERROR

        if self.language == "checktestdata":
            with main_path.open() as main_file:
                return self._exec_command(
                    self.run_command,
                    exec_code_map=format_exec_code_map,
                    stdin=main_file,
                    cwd=cwd,
                )

        if self.language == "viva":
            # Called as `viva validator.viva testcase.in`.
            result = self._exec_command(
                self.run_command + [main_path.resolve()],
                exec_code_map=format_exec_code_map,
                cwd=cwd,
            )
            return result

    def _exec_helper(self, *args, cwd, **kwargs):
        ret = self._exec_command(*args, **kwargs)
        judgemessage = cwd / "judgemessage.txt"
        judgeerror = cwd / "judgeerror.txt"
        if ret.err is None:
            ret.err = ""
        if judgeerror.is_file():
            ret.err = judgeerror.read_text(errors="replace")
        assert ret.err is not None
        if len(ret.err) == 0 and judgemessage.is_file():
            ret.err = judgemessage.read_text(errors="replace")
        if ret.err:
            ret.err = f"{self.name}: {ret.err}"

        return ret

    def run(
        self,
        testcase: testcase.Testcase,
        mode,
        constraints: Optional[ConstraintsDict] = None,
        args=None,
    ) -> ExecResult:
        raise Exception("Abstract method")


class InputValidator(Validator):
    """
    Validate an input file (such as "testcase.in"), called as:

        ./validator [arguments] < input

    Also supports checktestdata and viva files, with different invocation.
    """

    def __init__(self, problem, path, **kwargs):
        super().__init__(problem, path, "input_validators", **kwargs)

    validator_type = "input"

    source_dirs = ["input_validators", "input_format_validators"]

    def run(
        self,
        testcase,
        mode=Mode.INPUT,
        constraints: Optional[ConstraintsDict] = None,
        args=None,
    ) -> ExecResult:
        """
        Arguments
        ---------
        mode:
            must be Mode.INPUT
        """

        assert self.run_command is not None, "Validator should be built before running it"

        if mode == Mode.ANSWER:
            raise ValueError("InputValidators do not support Mode.ANSWER")
        if mode == Mode.INVALID:
            raise ValueError("InputValidators do no support Mode.INVALID")
        if mode == Mode.VALID_OUTPUT:
            raise ValueError("InputValidators do no support Mode.VALID_OUTPUT")

        cwd, constraints_path, arglist = self._run_helper(testcase, constraints, args)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        invocation = self.run_command.copy()

        with testcase.in_path.open() as in_file:
            ret = self._exec_helper(
                invocation + arglist,
                exec_code_map=validator_exec_code_map,
                stdin=in_file,
                cwd=cwd,
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

    def __init__(self, problem, path, **kwargs):
        super().__init__(problem, path, "answer_validators", **kwargs)

    validator_type = "answer"

    source_dirs = ["answer_validators", "answer_format_validators"]

    def run(
        self,
        testcase,
        mode=Mode.ANSWER,
        constraints: Optional[ConstraintsDict] = None,
        args=None,
    ) -> ExecResult:
        assert self.run_command is not None, "Validator should be built before running it"

        if mode == Mode.INPUT:
            raise ValueError("AnswerValidators do no support Mode.INPUT")
        if mode == Mode.INVALID:
            raise ValueError("AnswerValidators do no support Mode.INVALID")
        if mode == Mode.VALID_OUTPUT:
            raise ValueError("AnswerValidators do no support Mode.VALID_OUTPUT")

        cwd, constraints_path, arglist = self._run_helper(testcase, constraints, args)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            return Validator._run_format_validator(self, testcase, cwd)

        invocation = self.run_command + [testcase.in_path.resolve()]

        with testcase.ans_path.open() as ans_file:
            ret = self._exec_helper(
                invocation + arglist,
                exec_code_map=validator_exec_code_map,
                stdin=ans_file,
                cwd=cwd,
            )

        if constraints is not None:
            _merge_constraints(constraints_path, constraints)

        return ret


class OutputValidator(Validator):
    """
    Validate the output of a submission

       ./validator input answer feedbackdir [arguments from problem.yaml] < output
    """

    def __init__(self, problem, path, **kwargs):
        super().__init__(problem, path, "output_validators", **kwargs)

    validator_type = "output"

    # TODO #424: We should not support multiple output validators inside output_validator/.
    source_dirs = ["output_validator", "output_validators"]

    def run(
        self,
        testcase,  # TODO #102: fix type errors after setting type to Testcase
        mode,  # TODO #102: fix type errors after setting type to Mode | run.Run
        constraints: Optional[ConstraintsDict] = None,
        args=None,
    ) -> ExecResult:
        """
        Run this validator on the given testcase.

        Arguments
        ---------

        mode: either a run.Run (namely, when validating submission output) or a Mode
            (namely, when validation a testcase)

        Returns
        -------
        The ExecResult
        """

        assert self.run_command is not None, "Validator should be built before running it"

        if mode == Mode.INPUT:
            raise ValueError("OutputValidator do not support Mode.INPUT")

        in_path = testcase.in_path.resolve()
        ans_path = testcase.ans_path.resolve()
        if mode == Mode.ANSWER:
            path = ans_path
        elif mode == Mode.INVALID:
            if testcase.root != "invalid_output":
                raise ValueError(
                    "OutputValidator in Mode.INVALID should only be run for data/invalid_output"
                )
            path = testcase.out_path.resolve()
        elif mode == Mode.VALID_OUTPUT:
            if testcase.root != "valid_output":
                raise ValueError(
                    "OutputValidator in Mode.VALID_OUTPUT should only be run for data/valid_output"
                )
            path = testcase.out_path.resolve()
        else:
            assert mode != Mode.INPUT
            # mode is actually a Run
            path = mode.out_path
            in_path = mode.in_path

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            raise ValueError("Invalid output validator language")

        cwd, constraints_path, arglist = self._run_helper(testcase, constraints, args)
        if not isinstance(mode, Mode):
            cwd = mode.feedbackdir
        invocation = self.run_command + [in_path, ans_path, cwd]

        with path.open() as file:
            ret = self._exec_helper(
                invocation + arglist,
                exec_code_map=validator_exec_code_map,
                stdin=file,
                cwd=cwd,
            )

        if constraints is not None:
            _merge_constraints(constraints_path, constraints)

        return ret


AnyValidator = InputValidator | AnswerValidator | OutputValidator


# Checks if byte is printable or whitespace
INVALID_BYTES_WITH_OTHER: Final[re.Pattern[bytes]] = re.compile(b"[^\t\r\v\f\n\x20-\x7e]")
INVALID_BYTES: Final[re.Pattern[bytes]] = re.compile(b"[^\n\x20-\x7e]")


def _has_invalid_byte(bytes, *, other_whitespaces=False):
    if other_whitespaces:
        return INVALID_BYTES_WITH_OTHER.search(bytes) is not None
    else:
        return INVALID_BYTES.search(bytes) is not None


# assumes that the only possible whitespaces are space and newline
# allows \n\n
def _has_consecutive_whitespaces(bytes):
    for bad in [b" \n", b"  ", b"\n "]:
        if bytes.find(bad) >= 0:
            return True
    return False


def sanity_check(problem, path, bar, strict_whitespace=True):
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
    with open(path, "rb") as file:
        name = {
            ".in": "Input",
            ".ans": "Answer",
            ".out": "Output",
        }[path.suffix]
        file_bytes = file.read()
        if _has_invalid_byte(file_bytes, other_whitespaces=not strict_whitespace):
            bar.warn(f"{name} contains unexpected characters but was accepted!")
        elif len(file_bytes) == 0:
            bar.warn(f"{name} is empty but was accepted!")
        elif len(file_bytes) > 20_000_000:
            bar.warn(f"{name} is larger than 20MB!")
        elif (
            path.suffix in [".ans", ".out"]
            and len(file_bytes) > problem.limits.output * 1024 * 1024
        ):
            bar.warn(
                f"{name} exceeds output limit (set limits->output to at least {(len(file_bytes) + 1024 * 1024 - 1) // 1024 // 1024}MiB in problem.yaml)"
            )
        elif strict_whitespace:
            if file_bytes[0] in [ord(" "), ord("\n")]:
                bar.warn(f"{name} starts with whitespace but was accepted!")
            elif file_bytes[-1] != ord("\n"):
                bar.warn(f"{name} does not end with a newline but was accepted!")
            elif _has_consecutive_whitespaces(file_bytes):
                bar.warn(f"{name} contains consecutive whitespace characters but was accepted!")
