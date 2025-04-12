"""Test case"""

from typing import cast, Literal

from util import (
    ExecStatus,
    combine_hashes_dict,
    fatal,
    print_name,
    shorten_path,
    warn,
)
from colorama import Fore, Style
import config
import validate


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

    testdata_yaml: dict
        The YAML-parsed test data flags that apply to this test case.

    """

    def __init__(self, base_problem, path, *, short_path=None, print_warn=False):
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
        assert path.suffix == ".in" or path.suffixes == [".in", ".statement"]

        self.problem = base_problem

        # TODO add self.out_path
        if short_path is None:
            try:
                self.short_path = path.relative_to(self.problem.path / "data")
            except ValueError:
                fatal(f"Testcase {path} is not inside {self.problem.path / 'data'}.")
        else:
            self.short_path = short_path

        self.root = self.short_path.parts[0]

        self.in_path = path
        self.ans_path = (
            self.in_path.with_suffix(".ans")
            if path.suffix == ".in"
            else self.in_path.with_name(self.in_path.with_suffix("").stem + ".ans.statement")
        )
        self.out_path = (
            None
            if self.root not in ["valid_output", "invalid_output"]
            else self.in_path.with_suffix(".out")
        )
        # Display name: everything after data/.
        self.name = str(self.short_path.with_suffix(""))

        # Backwards compatibility support for `data/bad`.
        if self.root == "bad":
            if print_warn:
                warn("data/bad is deprecated. Use data/{invalid_input,invalid_answer} instead.")
            self.root = "invalid_answer" if self.ans_path.is_file() else "invalid_input"

    def __repr__(self):
        return self.name

    def with_suffix(self, ext):
        return self.in_path.with_suffix(ext)

    def testdata_yaml_validator_args(
        self,
        validator,  # TODO #102: Fix circular import when setting type to validate.AnyValidator
        bar,  # TODO #102: Type should probably be ProgressBar | PrintBar or something
    ) -> list[str]:
        """
        The flags specified in testdata.yaml for the given validator applying to this testcase.

        Returns
        -------

        A nonempty list of strings, such as ["space_change_sensitive", "case_sensitive"]
        or ["--max_N", "50"] or even [""].
        """
        key, name = (
            ("input_validator_args", validator.name)
            if isinstance(validator, validate.InputValidator)
            else ("output_validator_args", None)
        )

        path = self.problem.path / "data" / self.short_path
        return self.problem.get_testdata_yaml(
            path,
            cast(Literal["input_validator_args", "output_validator_args"], key),
            bar,
            name=name,
        )

    def validator_hashes(self, cls: type["validate.AnyValidator"], bar):
        """
        Returns
        -------
        a dict of objects
             hash =>
             - name
             - flags
             - hash
        indicating which validators will be run for this testcase.
        """
        assert cls in [validate.InputValidator, validate.AnswerValidator, validate.OutputValidator]
        validators = self.problem.validators(cls) or []

        d = dict()

        for validator in validators:
            flags = self.testdata_yaml_validator_args(validator, bar)
            if flags is False:
                continue
            flags_string = " ".join(flags)
            o = {
                "name": validator.name,
                "flags": flags_string,
                "hash": validator.hash,
            }
            h = combine_hashes_dict(o)
            # Don't actually store the somewhat useless validator hash.
            del o["hash"]
            d[h] = o

        return d

    def validate_format(
        self,
        mode: "validate.Mode",
        *,
        bar,
        constraints=None,
        warn_instead_of_error=False,
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
                assert self.root in config.INVALID_CASE_DIRECTORIES[:-1]

                ok = self.validate_format(
                    validate.Mode.INPUT,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
                if not ok or self.root == "invalid_input":
                    return ok

                assert not self.problem.interactive
                assert not self.problem.multi_pass

                ok = self.validate_format(
                    validate.Mode.ANSWER,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
                if not ok or self.root == "invalid_answer":
                    return ok

                return self._run_validators(
                    validate.Mode.INVALID,
                    self.problem.validators(validate.OutputValidator),
                    True,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                )
            case validate.Mode.VALID_OUTPUT:
                assert self.root == "valid_output"
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
        mode: "validate.Mode",
        validators,
        expect_rejection,
        *,
        bar,
        constraints=None,
        warn_instead_of_error=False,
    ) -> bool:
        args = []
        results = []
        for validator in validators:
            name = validator.name
            if type(validator) is validate.OutputValidator and mode == validate.Mode.ANSWER:
                args += ["case_sensitive", "space_change_sensitive"]
                name = f"{name} (ans)"
            flags = self.testdata_yaml_validator_args(validator, bar)
            if flags is False:
                continue
            flags = args if flags is None else flags + args

            ret = validator.run(self, mode=mode, constraints=constraints, args=flags)
            results.append(ret.status)

            message = name
            if flags:
                message += " [" + ", ".join(flags) + "]"
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
            else:
                data = ret.err

            if expect_rejection:
                bar.debug(
                    message,
                    data=data,
                    color=Fore.GREEN if ret.status == ExecStatus.REJECTED else Fore.YELLOW,
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
                    ret.status,
                    message,
                    data=data,
                    warn_instead_of_error=warn_instead_of_error,
                )

            if ret.status or self.root in [*config.INVALID_CASE_DIRECTORIES, "valid_output"]:
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
            success = ExecStatus.REJECTED in results
            if not success:
                msg = f"was not rejected by {mode} validation"
                if warn_instead_of_error:
                    bar.warn(msg)
                else:
                    bar.error(msg, resume=True)
        else:
            success = all(results)
            if success and mode in [validate.Mode.INPUT, validate.Mode.ANSWER]:
                validate.sanity_check(
                    self.problem,
                    self.in_path if mode == validate.Mode.INPUT else self.ans_path,
                    bar,
                )

        return success
