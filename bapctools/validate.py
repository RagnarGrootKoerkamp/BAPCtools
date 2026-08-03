import re
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Final, Optional, TYPE_CHECKING

from bapctools import config, languages, program
from bapctools.util import (
    ExecResult,
    ExecStatus,
    ProgressBar,
    remove_path,
    validator_exec_code_map,
)

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools import run, test_case
    from bapctools.problem import Problem


class Mode(Enum):
    """There are four validation modes for file validation"""

    INPUT = 1
    ANSWER = 2
    INVALID = 3
    VALID_OUTPUT = 4

    def __str__(self) -> str:
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


def _merge_constraints(constraints_path: Path, constraints: ConstraintsDict) -> None:
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
                vmin = min(c[3], vmin)
                vmax = max(c[4], vmin)
                low = min(c[5], low)
                high = max(c[6], high)
            constraints[loc] = (name, has_low, has_high, vmin, vmax, low, high)

        constraints_path.unlink()


class Validator(program.Program):
    """Base class for AnswerValidator, InputValidator, and OutputValidator.

    They can all take constraints.


    Validators implement a run method that runs the validator.

    It returns

    ExecResult: The result of running this validator on the given test case.
        ExecResult.status == ExecStatus.ACCEPTED  if the validator accepted.
        ExecResult.status == ExecStatus.REJECTED if the validator rejected.
    """

    FORMAT_VALIDATOR_LANGUAGES: Final[Sequence[languages.Language]] = [
        languages.CHECKTESTDATA,
        languages.COMPILED_CHECKTESTDATA,
        languages.VIVA,
    ]

    languages: Final[Sequence[str]] = languages.VALIDATOR_LANGUAGE_CODES

    def __repr__(self) -> str:
        return type(self).__name__ + ": " + str(self.path)

    def __init__(
        self,
        problem: "Problem",
        path: Path,
        subdir: str,
        skip_double_build_warning: bool = False,
        check_constraints: bool = False,
    ) -> None:
        super().__init__(
            problem,
            path,
            subdir,
            limits={
                "timeout": problem.limits.validation_time,
                "memory": problem.limits.validation_memory,
            },
            skip_double_build_warning=skip_double_build_warning,
            substitute_constants=True,
        )
        assert self.__class__ is not Validator  # Validator is abstract and may not be instantiated

        if check_constraints:
            self.tmpdir: Path = self.tmpdir.parent / (self.tmpdir.name + "_check_constraints")
        self.check_constraints = check_constraints

    def _run_helper(
        self,
        mode: "Mode | run.Run",
        test_case: "test_case.TestCase",
        constraints: Optional[ConstraintsDict],
        args: Optional[Sequence[str | Path]],
    ) -> tuple[Path, Optional[Path], Sequence[str | Path]]:
        """Helper method for the run method in subclasses.
        Return:
            cwd: a current working directory for this test case
            constraints_path: None or a path to the constraints file
            args: (possibly empty) list of arguments, possibly including --contraints_file
        """
        if isinstance(mode, Mode):
            if test_case.in_path.is_relative_to(self.problem.tmpdir):
                cwd = test_case.with_suffix(".feedbackdir")
            else:
                name = self.tmpdir.relative_to(self.problem.tmpdir)
                cwd = (
                    self.problem.tmpdir
                    / "tool_runs"
                    / name
                    / test_case.short_path.with_suffix(".feedbackdir")
                )
            remove_path(cwd)
            cwd.mkdir(parents=True, exist_ok=True)
        else:
            cwd = mode.feedbackdir

        arglist = []
        if args is not None:
            assert isinstance(args, list)
            arglist += args
        if constraints is not None:
            prefix = "input" if isinstance(self, InputValidator) else "answer"
            # NOTE: the constraints_path file is out of spec
            constraints_path = cwd / f"{prefix}_constraints_"
            arglist += ["--constraints_file", constraints_path]
        else:
            constraints_path = None

        return cwd, constraints_path, arglist

    # .ctd, .viva, or otherwise called as: ./validator [arguments] < inputfile.
    # It may not read/write files.
    def _run_format_validator(
        self, test_case: "test_case.TestCase", cwd: Path, args: Sequence[str | Path]
    ) -> ExecResult:
        assert self.language in Validator.FORMAT_VALIDATOR_LANGUAGES
        assert self.run_command is not None, "Validator should be built before running it"

        if isinstance(self, InputValidator):
            main_path = test_case.in_path
        elif isinstance(self, AnswerValidator):
            main_path = test_case.ans_path
        else:
            assert False  # now also catches OutputValidator

        if self.language == languages.COMPILED_CHECKTESTDATA:
            with main_path.open("rb") as main_file:
                return self._exec_command(
                    [*self.run_command, *args],
                    exec_code_map=validator_exec_code_map,
                    stdin=main_file,
                    cwd=cwd,
                )

        def format_exec_code_map(returncode: int) -> ExecStatus:
            if returncode == 0:
                return ExecStatus.ACCEPTED
            if returncode == 1:
                return ExecStatus.REJECTED
            if returncode == -9:
                return ExecStatus.TIMEOUT
            return ExecStatus.ERROR

        if self.language == languages.CHECKTESTDATA:
            with main_path.open("rb") as main_file:
                return self._exec_command(
                    [*self.run_command, *args],
                    exec_code_map=format_exec_code_map,
                    stdin=main_file,
                    cwd=cwd,
                )

        if self.language == languages.VIVA:
            # Called as `viva validator.viva testcase.in`.
            return self._exec_command(
                [*self.run_command, main_path.absolute(), *args],
                exec_code_map=format_exec_code_map,
                cwd=cwd,
            )

        assert False

    def _exec_helper(self, *args: Any, cwd: Path, **kwargs: Any) -> ExecResult:
        ret = self._exec_command(*args, cwd=cwd, **kwargs)
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
        test_case: "test_case.TestCase",
        mode: Mode,
        constraints: Optional[ConstraintsDict] = None,
        args: Optional[Sequence[str | Path]] = None,
    ) -> ExecResult:
        raise Exception("Abstract method")


class InputValidator(Validator):
    """
    Validate an input file (such as "testcase.in"), called as:

        ./validator [arguments] < input

    Also supports checktestdata and viva files, with different invocation.
    """

    validator_type: Final[str] = "input"

    source_dir: Final[str] = "input_validators"

    args_key: Final[str] = "input_validator_args"

    def __init__(self, problem: "Problem", path: Path, **kwargs: Any) -> None:
        super().__init__(problem, path, InputValidator.source_dir, **kwargs)

    def run(
        self,
        test_case: "test_case.TestCase",
        mode: Mode = Mode.INPUT,
        constraints: Optional[ConstraintsDict] = None,
        args: Optional[Sequence[str | Path]] = None,
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

        cwd, constraints_path, arglist = self._run_helper(mode, test_case, constraints, args)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            ret = Validator._run_format_validator(self, test_case, cwd, arglist)
        else:
            with test_case.in_path.open("rb") as in_file:
                ret = self._exec_helper(
                    [*self.run_command, *arglist],
                    exec_code_map=validator_exec_code_map,
                    stdin=in_file,
                    cwd=cwd,
                )

        if constraints is not None:
            assert constraints_path is not None
            _merge_constraints(constraints_path, constraints)

        return ret


class AnswerValidator(Validator):
    """
    Validate the default answer file "testcase.ans" (or "testcase.out" if it exists), called as:

        ./validator input < answer.

    Also supports checktestdata and viva files, with different invocation.
    """

    validator_type: Final[str] = "answer"

    source_dir: Final[str] = "answer_validators"

    args_key: Final[str] = "answer_validator_args"

    def __init__(self, problem: "Problem", path: Path, **kwargs: Any) -> None:
        super().__init__(problem, path, AnswerValidator.source_dir, **kwargs)

    def run(
        self,
        test_case: "test_case.TestCase",
        mode: Mode = Mode.ANSWER,
        constraints: Optional[ConstraintsDict] = None,
        args: Optional[Sequence[str | Path]] = None,
    ) -> ExecResult:
        assert self.run_command is not None, "Validator should be built before running it"

        if mode == Mode.INPUT:
            raise ValueError("AnswerValidators do no support Mode.INPUT")
        if mode == Mode.INVALID:
            raise ValueError("AnswerValidators do no support Mode.INVALID")
        if mode == Mode.VALID_OUTPUT:
            raise ValueError("AnswerValidators do no support Mode.VALID_OUTPUT")

        cwd, constraints_path, arglist = self._run_helper(mode, test_case, constraints, args)

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            ret = Validator._run_format_validator(self, test_case, cwd, arglist)
        else:
            with test_case.ans_path.open("rb") as ans_file:
                ret = self._exec_helper(
                    [*self.run_command, test_case.in_path.absolute(), *arglist],
                    exec_code_map=validator_exec_code_map,
                    stdin=ans_file,
                    cwd=cwd,
                )

        if constraints is not None:
            assert constraints_path is not None
            _merge_constraints(constraints_path, constraints)

        return ret


class OutputValidator(Validator):
    """
    Validate the output of a submission

       ./validator input answer feedbackdir [arguments from problem.yaml] < output
    """

    validator_type: Final[str] = "output"

    source_dir: Final[str] = "output_validator"

    args_key: Final[str] = "output_validator_args"

    def __init__(self, problem: "Problem", path: Path, **kwargs: Any) -> None:
        super().__init__(problem, path, OutputValidator.source_dir, **kwargs)

    def run(
        self,
        test_case: "test_case.TestCase",
        mode: "Mode | run.Run",
        constraints: Optional[ConstraintsDict] = None,
        args: Optional[Sequence[str | Path]] = None,
    ) -> ExecResult:
        """
        Run this validator on the given test case.

        Arguments
        ---------

        mode: either a run.Run (namely, when validating submission output) or a Mode
            (namely, when validating a test case)

        Returns
        -------
        The ExecResult
        """

        assert self.run_command is not None, "Validator should be built before running it"

        if mode == Mode.INPUT:
            raise ValueError("OutputValidator does not support Mode.INPUT")

        in_path = test_case.in_path.absolute()
        ans_path = test_case.ans_path.absolute()
        if mode == Mode.ANSWER:
            path = ans_path
        elif mode == Mode.INVALID:
            if test_case.root != "invalid_output":
                raise ValueError(
                    "OutputValidator in Mode.INVALID should only be run for data/invalid_output"
                )
            assert test_case.out_path is not None
            path = test_case.out_path.absolute()
        elif mode == Mode.VALID_OUTPUT:
            assert test_case.out_path is not None
            path = test_case.out_path.absolute()
        else:
            # mode is actually a Run
            path = mode.out_path
            in_path = mode.in_path  # relevant for multipass

        if self.language in Validator.FORMAT_VALIDATOR_LANGUAGES:
            raise ValueError("Invalid output validator language")

        cwd, constraints_path, arglist = self._run_helper(mode, test_case, constraints, args)

        with path.open("rb") as file:
            ret = self._exec_helper(
                [*self.run_command, in_path, ans_path, cwd, *arglist],
                exec_code_map=validator_exec_code_map,
                stdin=file,
                cwd=cwd,
            )

        if constraints is not None:
            assert constraints_path is not None
            _merge_constraints(constraints_path, constraints)

        return ret


AnyValidator = InputValidator | AnswerValidator | OutputValidator


# Checks if byte is printable or whitespace
INVALID_BYTES_WITH_OTHER: Final[re.Pattern[bytes]] = re.compile(b"[^\t\r\v\f\n\x20-\x7e]")
INVALID_BYTES: Final[re.Pattern[bytes]] = re.compile(b"[^\n\x20-\x7e]")


def _has_invalid_byte(bytes: bytes, *, other_whitespaces: bool = False) -> bool:
    if other_whitespaces:
        return INVALID_BYTES_WITH_OTHER.search(bytes) is not None
    else:
        return INVALID_BYTES.search(bytes) is not None


# assumes that the only possible whitespaces are space and newline
# allows \n\n
def _has_consecutive_whitespaces(bytes: bytes) -> bool:
    for bad in [b" \n", b"  ", b"\n "]:
        if bytes.find(bad) >= 0:
            return True
    return False


def sanity_check(
    problem: "Problem", path: Path, bar: ProgressBar, strict_whitespace: bool = True
) -> None:
    """
    Does some generic checks on input, answer, or output files of a test case, including

    - no unreadable characters
    - not too large

    if any of this is violated a warning is printed.
    use --no-test-case-sanity-checks to skip this

    args:
        strict_whitespace: Also check
        - no weird consecutive whitespaces ('  ', '\n ', ' \n')
        - no other_whitespaces (like '\t')
        - no whitespace at start of file
        - ensures newline at end of file
    """
    if config.args.no_test_case_sanity_checks:
        return

    assert path.exists()

    name = {
        ".in": "Input",
        ".ans": "Answer",
        ".out": "Output",
    }[path.suffix]

    file_bytes = path.read_bytes()

    if len(file_bytes) == 0:
        # only allow empty files for interactive or multi-pass .ans
        if not (path.suffix == ".ans" and (problem.interactive or problem.multi_pass)):
            bar.warn(f"{name} is empty but was accepted!")
        return
    else:
        # enforce empty .ans file for interactive
        if problem.interactive and path.suffix == ".ans":
            bar.warn(f"use empty .ans file for {problem.settings.type_name()} problem")
        return  # Since the .ans file MUST be empty, the other sanity checks can be skipped.

    # check file size limits
    # TODO: consider time limit (more time => larger file limit)?
    file_size_limit = 20  # in MiB
    inMiB = 1024**2
    assert config.ICPC_FILE_LIMIT > file_size_limit
    if len(file_bytes) >= config.ICPC_FILE_LIMIT * inMiB:
        bar.warn(f"{name} is too large for the ICPC Archive (limit {config.ICPC_FILE_LIMIT}MiB)!")
    elif len(file_bytes) > file_size_limit * inMiB:
        bar.warn(f"{name} is larger than {file_size_limit}MiB!")

    # check output limits
    if path.suffix in [".ans", ".out"]:
        if len(file_bytes) > problem.limits.output * inMiB:
            new_limit = (len(file_bytes) + inMiB - 1) // inMiB
            bar.warn(
                f"{name} exceeds output limit (set limits->output to at least {new_limit}MiB in problem.yaml)"
            )
        elif 2 * len(file_bytes) > problem.limits.output * inMiB:
            bar.warn(f"{name} is close to output limit (you should consider doubling it)")

    # check content
    if _has_invalid_byte(file_bytes, other_whitespaces=not strict_whitespace):
        bar.warn(f"{name} contains unexpected characters but was accepted!")
    if strict_whitespace:
        if file_bytes[0] in b" \n":
            bar.warn(f"{name} starts with whitespace but was accepted!")
        if not file_bytes.endswith(b"\n"):
            bar.warn(f"{name} does not end with a newline but was accepted!")
        if _has_consecutive_whitespaces(file_bytes):
            bar.warn(f"{name} contains consecutive whitespace characters but was accepted!")


def _sanity_check_override(file_bytes: bytes, bar: ProgressBar, name: str) -> None:
    if len(file_bytes) == 0:
        return
    if _has_invalid_byte(file_bytes, other_whitespaces=False):
        bar.warn(f"{name} contains unexpected characters")
    if file_bytes[0] in b" \n":
        bar.warn(f"{name} starts with whitespace")
    if not file_bytes.endswith(b"\n"):
        bar.warn(f"{name} does not end with a newline")
    if _has_consecutive_whitespaces(file_bytes):
        bar.warn(f"{name} contains consecutive whitespace characters")


def sanity_check_override(problem: "Problem", path: Path, bar: ProgressBar) -> None:
    """
    Does some generic checks on override files, including

    - no unreadable characters
    - no weird consecutive whitespaces ('  ', '\n ', ' \n')
    - no other_whitespaces (like '\t')
    - ensures newline at end of file

    if any of this is violated a warning is printed.
    use --no-test-case-sanity-checks to skip this
    """
    if config.args.no_test_case_sanity_checks:
        return

    assert path.exists()

    name = {
        ".in.statement": "Statement input",
        ".ans.statement": "Statement answer",
        ".in.download": "Download input",
        ".ans.download": "Download answer",
    }["".join(path.suffixes[-2:])]
    _sanity_check_override(path.read_bytes(), bar, name)


def check_interaction(
    problem: "Problem", path: Path, bar: ProgressBar, *, startswith: bytes = b""
) -> bool:
    """
    Checks the override as well as some specific checks for .interaction files, including

    - each line starts with '>', '<' or is '---'
    - tries to guess if '>' and '<' have been mixed up if startswith is given

    if any of this is violated a warning is printed.
    use --no-test-case-sanity-checks to skip all optional checks
    """
    assert path.exists()

    file_bytes = path.read_bytes()

    # split into passes
    lines = file_bytes.splitlines(keepends=True)
    passes = []
    current_pass: list[bytes] = []
    whitespace_issue = False
    for line in lines:
        if line.startswith(b"---"):
            passes.append(current_pass)
            current_pass = []
            if line == b"---\n":
                pass
            elif line[3:].isspace():
                whitespace_issue = True
            else:
                bar.error("Interaction separator is followed by unexpected characters")
                return False
        else:
            current_pass.append(line)
    passes.append(current_pass)

    if len(passes) > 1 and not problem.multi_pass:
        bar.error("Interaction contains multiples passes but problem is not multi-pass")
        return False

    for line in sum(passes, []):
        if line.startswith(b"<"):
            continue
        if line.startswith(b">"):
            continue
        bar.error("Interaction is invalid, lines must start with '<' or '>'")
        return False

    if config.args.no_test_case_sanity_checks:
        return True

    # detected earlier
    if whitespace_issue:
        bar.warn("Interaction separator is followed by unexpected whitespace characters")

    # parse interaction for each pass
    for p, lines in enumerate(passes, start=1):
        has_jury = False
        has_team = False
        has_jury_after_team = False

        parsed = []
        for line in lines:
            if line.startswith(b"<"):
                has_jury = True
                has_jury_after_team |= has_team
            else:
                assert line.startswith(b">")
                has_team = True
            parsed.append(line[1:])

        data = b"".join(parsed)
        name = f"Interaction pass {p}" if problem.multi_pass else "Interaction"
        _sanity_check_override(data, bar, name)

        if not has_jury:
            bar.warn(f"{name} has no team <- jury output")
        elif not problem.interactive and has_jury_after_team:
            bar.warn(f"{name} for non interactive problem has interleaved communication")
        if not has_team:
            bar.warn(f"{name} has no team -> jury output")

    # try to check if '>' and '<' are used correctly
    assert len(startswith) <= 1
    if startswith and not file_bytes.startswith(startswith):
        bar.warn("Did you mix up '>' and '<'? ('>' is team -> jury)")
    return True
