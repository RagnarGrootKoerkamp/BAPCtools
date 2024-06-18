""" Test case """

import os
from pathlib import Path
from typing import Type, Literal

from util import (
    fatal,
    is_relative_to,
    combine_hashes_dict,
    shorten_path,
    print_name,
    warn,
    ExecStatus,
)
from colorama import Fore, Style
from validate import Validator, InputValidator, AnswerValidator, OutputValidator, Mode, sanity_check
import config


class Testcase:
    """
    A single test case. It consists of files with matching base names, typically

    * an input file, sometimes called "the input", with extension `.in`, such as `petersen.in`
    * a default answer file, sometimes called "the answer", with extension `.ans`, such as `petersen.ans`

    Test cases in `data/invalid_inputs` consist only of an input file. [Not implemnted:] Test cases
    in `data/invalid_outputs` additionally consist of an output file, with extension `.out`.

    As a rule of thumb, test cases have different inputs. To be precise, test cases in
    the same directory must have different inputs, except for test cases below `invalid_answers`
    and [not implemented] `invalid_outputs`. Moreover, test cases in different directories with
    the same base name, such as `sample/petersen` and `secret/cubic/petersen`, may have identical inputs;
    this commonly happens when the first test case was included from `sample` into `secret/cubic`.

    Attributes
    ----------

    problem: Problem
        The underlying problem that this test case belongs to.

    name: str
        The name of this test case, relative to `data`, like `secret/cubic/petersen`.

    root: str
        The name of the topmost directory below `data` containing this test case, like `secret` or `invalid_inputs`.

    short_path: Path
        The path to the input of this test case, relative to `data`, like `secret/cubic/petersen.in`.

    in_path: Path
        Like `hamiltonicity/data/secret/cubic/petersen.in`.

    ans_path: Path
        Like `hamiltonicity/data/secret/cubic/petersen.ans`.

    testdata_yaml: dict
        The YAML-parsed test data flags that apply to this test case.

    """

    def __init__(self, base_problem, path: Path, *, short_path=None, print_warn=False):
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
        assert path.suffix == '.in' or path.suffixes == [".in", ".statement"]

        self.problem = base_problem

        # TODO add self.out_path
        if short_path is None:
            try:
                self.short_path = path.relative_to(self.problem.path / 'data')
            except ValueError:
                fatal(f"Testcase {path} is not inside {self.problem.path / 'data'}.")
        else:
            self.short_path = short_path

        self.root = self.short_path.parts[0]

        self.in_path = path
        self.ans_path = (
            self.in_path.with_suffix('.ans')
            if path.suffix == '.in'
            else self.in_path.with_name(self.in_path.with_suffix('').stem + '.ans.statement')
        )
        self.out_path = None if self.root != 'invalid_outputs' else self.in_path.with_suffix('.out')
        # Display name: everything after data/.
        self.name = str(self.short_path.with_suffix(''))

        # Backwards compatibility support for `data/bad`.
        if self.root == 'bad':
            if print_warn:
                warn('data/bad is deprecated. Use data/{invalid_inputs,invalid_answers} instead.')
            self.root = 'invalid_answers' if self.ans_path.is_file() else 'invalid_inputs'

    def __repr__(self):
        return self.name

    def with_suffix(self, ext):
        return self.in_path.with_suffix(ext)

    def testdata_yaml_validator_flags(self, validator, bar) -> list[str] | None:
        """
        The flags specified in testdata.yaml for the given validator applying to this testcase.

        Returns
        -------

        A nonempty list of strings, such as ['space_change_sensitive', 'case_sensitive']
        or ["--max_N", "50"] or even [""].
        None if no flags were found
        """
        if not isinstance(validator, Validator):
            raise ValueError(f"Validator expected, got {validator}")

        key, name = (
            ('input_validator_flags', validator.name)
            if isinstance(validator, InputValidator)
            else ('output_validator_flags', None)
        )

        path = self.problem.path / 'data' / self.short_path
        flags = self.problem.get_testdata_yaml(path, key, bar, name=name)

        if flags is None:
            return None
        if not isinstance(flags, str):
            fatal(f'{key} must be a string in testdata.yaml, got {flags}')
        return flags.split()

    def validator_hashes(self, cls: Type[Validator], bar):
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
        assert cls in [InputValidator, AnswerValidator, OutputValidator]
        validators = self.problem.validators(cls) or []

        d = dict()

        for validator in validators:
            flags = self.testdata_yaml_validator_flags(validator, bar)
            if flags is False:
                continue
            flags_string = ' '.join(flags) if flags is not None else None
            o = {
                'name': validator.name,
                'flags': flags_string,
                'hash': validator.hash,
            }
            h = combine_hashes_dict(o)
            # Don't actually store the somewhat useless validator hash.
            del o['hash']
            d[h] = o

        return d

    def validate_format(
        self,
        mode: Mode,
        *,
        bar,
        constraints=None,
        warn_instead_of_error=False,
        args=None,
    ) -> bool:
        check_constraints = constraints is not None

        match mode:
            case Mode.INPUT:
                return self._run_validators(
                    Mode.INPUT,
                    self.problem.validators(InputValidator, check_constraints=check_constraints),
                    self.root == 'invalid_inputs',
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                    args=args,
                )
            case Mode.ANSWER:
                return self._run_validators(
                    Mode.ANSWER,
                    self.problem.validators(AnswerValidator, check_constraints=check_constraints)
                    + self.problem.validators(OutputValidator, check_constraints=check_constraints),
                    self.root == 'invalid_answers',
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                    args=args,
                )
            case Mode.INVALID:
                assert self.root in config.INVALID_CASE_DIRECTORIES[:-1]

                ok = self.validate_format(
                    Mode.INPUT,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                    args=args,
                )
                if not ok or self.root == 'invalid_inputs':
                    return ok

                assert not self.problem.interactive
                assert not self.problem.multipass

                ok = self.validate_format(
                    Mode.ANSWER,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                    args=args,
                )
                if not ok or self.root == 'invalid_answers':
                    return ok

                return self._run_validators(
                    Mode.INVALID,
                    self.problem.validators(OutputValidator),
                    True,
                    bar=bar,
                    constraints=constraints,
                    warn_instead_of_error=warn_instead_of_error,
                    args=args,
                )
            case _:
                raise ValueError

    def _run_validators(
        self,
        mode: Mode,
        validators,
        expect_rejection,
        *,
        bar,
        constraints=None,
        warn_instead_of_error=False,
        args=None,
    ) -> bool:
        if args is None:
            args = []
        results = []
        for validator in validators:
            name = validator.name
            if type(validator) == OutputValidator and mode == Mode.ANSWER:
                args += ['case_sensitive', 'space_change_sensitive']
                name = f'{name} (ans)'
            flags = self.testdata_yaml_validator_flags(validator, bar)
            if flags is False:
                continue
            flags = args if flags is None else flags + args

            ret = validator.run(self, mode=mode, constraints=constraints, args=flags)
            results.append(ret.status)

            message = name
            if flags:
                message += ' [' + ', '.join(flags) + ']'
            message += ': '
            if ret.status:
                message += 'accepted'
            elif ret.status == ExecStatus.TIMEOUT:
                message += 'timeout'
            elif ret.status == ExecStatus.REJECTED:
                message += 'rejected'
            else:
                message += 'crashed'

            # Print stdout and stderr whenever something is printed
            data = ''
            if not (ret.status or expect_rejection) or config.args.error:
                if ret.err and ret.out:
                    ret.out = (
                        ret.err
                        + f'\n{Fore.RED}VALIDATOR STDOUT{Style.RESET_ALL}\n'
                        + Fore.YELLOW
                        + ret.out
                    )
                elif ret.err:
                    data = ret.err
                elif ret.out:
                    data = ret.out

                if mode == Mode.INPUT:
                    file = self.in_path
                elif mode == Mode.ANSWER:
                    file = self.ans_path
                elif mode == Mode.INVALID:
                    assert self.out_path is not None
                    file = self.out_path

                data += (
                    f'{Style.RESET_ALL}-> {shorten_path(self.problem, file.parent) / file.name}\n'
                )
            else:
                data = ret.err

            if ret.returncode == 0:
                bar.part_done(
                    False,
                    message,
                    data='Exit code 0, did you forget to exit with WA or AC?',
                    warn_instead_of_error=warn_instead_of_error,
                )
            elif expect_rejection:
                bar.debug(
                    message,
                    data=data,
                    color=Fore.GREEN if ret.status == ExecStatus.REJECTED else Fore.YELLOW,
                )
            else:
                bar.part_done(
                    ret.status,
                    message,
                    data=data,
                    warn_instead_of_error=warn_instead_of_error,
                )

            if ret.status or self.root in config.INVALID_CASE_DIRECTORIES:
                continue

            # Move testcase to destination directory if specified.
            if config.args.move_to:
                infile = self.in_path
                targetdir = self.problem.path / config.args.move_to
                targetdir.mkdir(parents=True, exist_ok=True)
                intarget = targetdir / infile.name
                infile.rename(intarget)
                bar.log('Moved to ' + print_name(intarget))
                ansfile = self.ans_path
                if ansfile.is_file():
                    anstarget = intarget.with_suffix('.ans')
                    ansfile.rename(anstarget)
                    bar.log('Moved to ' + print_name(anstarget))

            # Remove testcase if specified.
            elif mode == Mode.INPUT and config.args.remove:
                bar.log(Fore.RED + 'REMOVING TESTCASE!' + Style.RESET_ALL)
                if self.in_path.exists():
                    self.in_path.unlink()
                if self.ans_path.exists():
                    self.ans_path.unlink()

            break

        if expect_rejection:
            success = ExecStatus.REJECTED in results
            if not success:
                bar.error(f'was not rejected by {mode} validation', resume=True)
        else:
            success = all(results)
            if success:
                sanity_check(self.in_path if mode == Mode.INPUT else self.ans_path, bar)

        return success
