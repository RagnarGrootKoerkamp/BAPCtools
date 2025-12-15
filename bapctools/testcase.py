"""Test case"""

from collections.abc import Sequence
from colorama import Fore, Style
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from bapctools import config, validate
from bapctools.util import (
    BAR_TYPE,
    combine_hashes_dict,
    ExecStatus,
    fatal,
    print_name,
    ProgressBar,
    shorten_path,
)

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools import problem


# TODO #102: Consistently separate the compound noun "test case", e.g. "TestCase" or "test_case"
class Testcase:
    """
    A single test case. It consists of files with matching base names, typically

    * an input file, sometimes called "the input", with extension `.in`, such as `petersen.in`
    * a default answer file, sometimes called "the answer", with extension `.ans`, such as `petersen.ans`

    Test cases in `data/invalid_input` consist only of an input file. Test cases in `data/valid_output`
    or `data/invalid_output` additionally consist of an output file, with extension `.out`.

    As a rule of thumb, test cases have different inputs. To be precise, test cases in
    the same directory must have different inputs, except for test cases below `invalid_answer`,
    `invalid_output`, and `valid_output`. Moreover, test cases in different directories with
    the same base name, such as `sample/petersen` and `secret/cubic/petersen`, may have identical inputs;
    this commonly happens when the first test case was included from `sample` into `secret/cubic`.

    Attributes
    ----------

    problem: Problem
        The underlying problem that this test case belongs to.

    name: str
        The name of this test case, relative to `data`, like `secret/cubic/petersen`.

    root: str
        The name of the topmost directory below `data` containing this test case, like `secret` or `invalid_input`.

    short_path: Path
        The path to the input of this test case, relative to `data`, like `secret/cubic/petersen.in`.

    in_path: Path
        Like `hamiltonicity/data/secret/cubic/petersen.in`.

    ans_path: Path
        Like `hamiltonicity/data/secret/cubic/petersen.ans`.

    out_path: Path
        Like `hamiltonicity/data/secret/cubic/petersen.out`.

    """

    def __init__(
        self,
        base_problem: "problem.Problem",
        path: Path,
        *,
        short_path: Optional[Path] = None,
    ):
        """
        Arguments
        ---------
        path: Path
            The path to the testcase's input file, like `data/secret/cubic/petersen.in`

        short_path: Path
            Testcases outside problem/data must pass in the short_path explicitly.  In that case, `path`
            is the (absolute) path to the input file, and `short_path` is used as the equivalent of the testcase's
            path relative to  `problem.path / 'data'`.
        """
        assert path.suffix == ".in"

        self.problem = base_problem

        if short_path is None:
            try:
                self.short_path: Path = path.relative_to(self.problem.path / "data")
            except ValueError:
                fatal(f"Testcase {path} is not inside {self.problem.path / 'data'}.")
        else:
            self.short_path = short_path

        self.root: str = self.short_path.parts[0]

        self.in_path: Path = path
        self.ans_path: Path = self.in_path.with_suffix(".ans")
        self.out_path: Optional[Path] = (
            self.in_path.with_suffix(".out")
            if self.root in ["valid_output", "invalid_output"]
            or self.in_path.with_suffix(".out").is_file()
            else None
        )

        # Display name: everything after data/.
        self.name: str = str(self.short_path.with_suffix(""))

    def __repr__(self) -> str:
        return self.name

    def with_suffix(self, ext: str) -> Path:
        return self.in_path.with_suffix(ext)

    def get_test_case_yaml(self, bar: BAR_TYPE) -> "problem.TestGroup":
        assert self.in_path.is_file()
        return self.problem.get_test_case_yaml(
            self.problem.path / "data" / self.short_path.with_suffix(".yaml"),
            bar,
        )

    def validator_hashes(
        self, cls: type[validate.AnyValidator], bar: BAR_TYPE
    ) -> dict[str, dict[str, str]]:
        """
        Returns
        -------
        a dict of objects
             hash =>
             - name
             - flags
        indicating which validators will be run for this testcase.
        """
        assert cls in [validate.InputValidator, validate.AnswerValidator, validate.OutputValidator]
        validators = self.problem.validators(cls)

        d = dict()

        for validator in validators:
            flags = self.get_test_case_yaml(bar).get_args(validator)
            flags_string = " ".join(flags)
            h = combine_hashes_dict(
                {
                    "name": validator.name,
                    "flags": flags_string,
                    "hash": validator.hash,
                }
            )
            d[h] = {
                "name": validator.name,
                "flags": flags_string,
            }

        return d

    def validate_format(
        self,
        mode: validate.Mode,
        *,
        bar: ProgressBar,
        constraints: Optional[validate.ConstraintsDict] = None,
        warn_instead_of_error: bool = False,
    ) -> bool:
        check_constraints = constraints is not None

        match mode:
            case validate.Mode.INPUT:
                return self._run_validators(
                    validate.Mode.INPUT,
                    self.problem.validators(
                        validate.InputValidator, check_constraints=check_constraints
                    ),
                    self.root == "invalid_input",
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
            case validate.Mode.ANSWER:
                return self._run_validators(
                    validate.Mode.ANSWER,
                    self.problem.validators(
                        validate.AnswerValidator, check_constraints=check_constraints
                    ),
                    self.root == "invalid_answer",
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
            case validate.Mode.INVALID:
                assert self.root in config.INVALID_CASE_DIRECTORIES

                ok = self.validate_format(
                    validate.Mode.INPUT,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
                if not ok or self.root == "invalid_input":
                    return ok

                assert not self.problem.interactive

                ok = self.validate_format(
                    validate.Mode.ANSWER,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
                if not ok or self.root == "invalid_answer":
                    return ok

                assert not self.problem.multi_pass

                return self._run_validators(
                    validate.Mode.INVALID,
                    self.problem.validators(validate.OutputValidator),
                    True,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
            case validate.Mode.VALID_OUTPUT:
                assert not self.problem.interactive
                assert not self.problem.multi_pass

                ok = self.validate_format(
                    validate.Mode.INPUT,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
                if not ok:
                    return ok

                ok = self.validate_format(
                    validate.Mode.ANSWER,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
                if not ok:
                    return ok

                return self._run_validators(
                    validate.Mode.VALID_OUTPUT,
                    self.problem.validators(validate.OutputValidator),
                    False,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
            case _:
                raise ValueError

    def _run_validators(
        self,
        mode: validate.Mode,
        validators: Sequence[validate.AnyValidator],
        expect_rejection: bool,
        *,
        bar: ProgressBar,
        constraints: Optional[validate.ConstraintsDict] = None,
        warn_instead_of_error: bool = False,
    ) -> bool:
        results = []
        output_validator_crash = False
        for validator in validators:
            name = validator.name
            args = []
            if isinstance(validator, validate.OutputValidator) and mode == validate.Mode.ANSWER:
                args += ["case_sensitive", "space_change_sensitive"]
                name = f"{name} (ans)"
            args = [*args, *self.get_test_case_yaml(bar).get_args(validator)]

            ret = validator.run(self, mode=mode, constraints=constraints, args=args)
            results.append(ret.status)

            message = name
            if args:
                message += " [" + ", ".join(args) + "]"
            message += ": "
            if ret.status:
                message += "accepted"
            elif ret.status == ExecStatus.TIMEOUT:
                message += "timeout"
            elif ret.status == ExecStatus.REJECTED:
                message += "rejected"
            else:
                message += "crashed"

            # Print stdout and stderr whenever something is printed
            data = ""
            if not (ret.status or expect_rejection) or config.args.error:
                if ret.err and ret.out:
                    ret.out = (
                        ret.err
                        + f"\n{Fore.RED}VALIDATOR STDOUT{Style.RESET_ALL}\n"
                        + Fore.YELLOW
                        + ret.out
                    )
                elif ret.err:
                    data = ret.err
                elif ret.out:
                    data = ret.out

                if mode == validate.Mode.INPUT:
                    file = self.in_path
                elif mode == validate.Mode.ANSWER:
                    file = self.ans_path
                elif mode in [validate.Mode.INVALID, validate.Mode.VALID_OUTPUT]:
                    assert self.out_path is not None
                    file = self.out_path

                data += (
                    f"{Style.RESET_ALL}-> {shorten_path(self.problem, file.parent) / file.name}\n"
                )
            elif ret.err:
                data = ret.err

            if expect_rejection:
                warn = False
                if (
                    isinstance(validator, validate.OutputValidator)
                    and ret.status == ExecStatus.ERROR
                ):
                    output_validator_crash = True
                    warn = True
                elif ret.status == ExecStatus.TIMEOUT:
                    warn = True
                else:
                    color = Fore.GREEN if ret.status == ExecStatus.REJECTED else Fore.YELLOW

                if warn:
                    bar.part_done(
                        False,
                        message,
                        data=data,
                        warn_instead_of_error=warn_instead_of_error,
                    )
                else:
                    bar.debug(
                        message,
                        data=data,
                        color=color,
                    )
            elif ret.status == ExecStatus.ERROR and ret.returncode == 0:
                bar.part_done(
                    False,
                    message,
                    data="Exit code 0, did you forget to exit with WA or AC?",
                    warn_instead_of_error=warn_instead_of_error,
                )
            else:
                bar.part_done(
                    bool(ret.status),
                    message,
                    data=data,
                    warn_instead_of_error=warn_instead_of_error,
                )

            if (
                ret.status
                or expect_rejection
                or self.root in [*config.INVALID_CASE_DIRECTORIES, "valid_output"]
            ):
                continue

            # Move testcase to destination directory if specified.
            if config.args.move_to:
                infile = self.in_path
                targetdir = self.problem.path / config.args.move_to
                targetdir.mkdir(parents=True, exist_ok=True)
                intarget = targetdir / infile.name
                infile.rename(intarget)
                bar.log("Moved to " + print_name(intarget))
                ansfile = self.ans_path
                if ansfile.is_file():
                    anstarget = intarget.with_suffix(".ans")
                    ansfile.rename(anstarget)
                    bar.log("Moved to " + print_name(anstarget))

            # Remove testcase if specified.
            elif mode == validate.Mode.INPUT and config.args.remove:
                bar.log(Fore.RED + "REMOVING TESTCASE!" + Style.RESET_ALL)
                if self.in_path.exists():
                    self.in_path.unlink()
                if self.ans_path.exists():
                    self.ans_path.unlink()

            break

        if expect_rejection:
            issues = []
            if all(results):
                issues.append("All validators accepted.")
            elif ExecStatus.REJECTED not in results:
                issues.append(f"At least one validator must exit with {config.RTV_WA}.")
            elif ExecStatus.TIMEOUT in results:
                issues.append("Validator timed out.")
            if output_validator_crash:
                issues.append("Output Validator crashed.")

            success = not issues
            if not success:
                msg = f"was not properly rejected by {mode} validation. {' '.join(issues)}"
                if warn_instead_of_error:
                    bar.warn(msg)
                else:
                    bar.error(msg, resume=True)
        else:
            success = all(results)
            if success:
                main_path: Optional[Path] = None
                if mode == validate.Mode.INPUT:
                    main_path = self.in_path
                elif mode == validate.Mode.ANSWER:
                    main_path = self.ans_path
                elif mode == validate.Mode.VALID_OUTPUT and self.root not in [
                    "valid_output",
                    "invalid_output",
                ]:
                    main_path = self.out_path

                if main_path is not None:
                    validate.sanity_check(
                        self.problem,
                        main_path,
                        bar,
                    )

        return success
