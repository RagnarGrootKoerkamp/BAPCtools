""" Test case """

import os
from pathlib import Path
from typing import Type

from util import (
    fatal,
    is_relative_to,
    combine_hashes_dict,
    shorten_path,
    print_name,
    warn,
    error,
    log,
)
from colorama import Fore, Style
import validate
import config


class Testcase:
    """
    # Testcases outside problem/data must pass in the short_path explicitly.
    # In that case, `path` is the (absolute) path to the `.in` file being
    # tested, and `short_path` is the name of the testcase relative to
    # `problem.path / 'data'`.
    """

    def __init__(self, base_problem, path: Path, *, short_path=None):
        assert path.suffix == '.in' or path.suffixes == [".in", ".statement"]

        self.problem = base_problem

        self.in_path = path
        self.ans_path = (
            self.in_path.with_suffix('.ans')
            if path.suffix == '.in'
            else self.in_path.with_name(self.in_path.with_suffix('').stem + '.ans.statement')
        )
        # TODO add self.out_path
        if short_path is None:
            try:
                self.short_path = path.relative_to(self.problem.path / 'data')
            except ValueError:
                fatal(f"Testcase {path} is not inside {self.problem.path / 'data'}.")
        else:
            assert short_path is not None
            self.short_path = short_path

        # Display name: everything after data/.
        self.name = str(self.short_path.with_suffix(''))

        self.root = self.short_path.parts[0]

        # Backwards compatibility support for `data/bad`.
        if self.root == 'bad':
            warn('data/bad is deprecated. Use data/{invalid_inputs,invalid_answers} instead.')
            self.root = 'invalid_inputs' if self.ans_path.is_file() else 'invalid_answers'
        assert self.root in [
            'invalid_inputs',
            'invalid_answers',
            'secret',
            'sample',
            'test',
        ], self.root  # TODO add invalid_outputs

        self.included = False
        if path.is_symlink():
            include_target = Path(os.path.normpath(path.parent / os.readlink(path)))
            if is_relative_to(self.problem.path / 'data', include_target):
                self.included = True
            else:
                # The case is an unlisted cases included from generators/.
                pass

        # Get the testdata.yaml content for this testcase.
        # Read using the short_path instead of the in_path, because during
        # generate the testcase will live in a temporary directory, where
        # testdata.yaml doesn't exist.
        self.testdata_yaml = self.problem.get_testdata_yaml(
            self.problem.path / 'data' / self.short_path
        )

    def with_suffix(self, ext):
        return self.in_path.with_suffix(ext)

    # Return the flags specified in testdata.yaml for the given validator,
    # None if no flags were found, or False if this validator should be skipped.
    # If `split`, split the string by spaces.
    def testdata_yaml_validator_flags(self, validator_type, validator, split=True):
        # Do not use flags when using the default output validator.
        if self.problem.settings.validation == 'default' and validator_type == 'output':
            return None

        if self.testdata_yaml is None:
            return None
        key = 'input_validator_flags' if validator_type == 'input' else 'output_validator_flags'
        if key not in self.testdata_yaml:
            return None
        flags = self.testdata_yaml[key]
        # Note: support for lists/dicts for was removed in #259.
        if not isinstance(flags, str):
            fatal(f'{key} must be a string in testdata.yaml')
        return flags.split() if split else flags

    def validator_hashes(self, cls: Type[validate.Validator]):
        """
        Returns: a dict of obje
             hash =>
             - name
             - flags
             - hash
        indicating which validators will be run for the current testcase.
        """
        assert cls in [validate.InputValidator, validate.AnswerValidator]
        validators = self.problem.validators(cls) or []

        d = dict()

        for validator in validators:
            flags = self.testdata_yaml_validator_flags(cls, validator, split=False)
            if flags is False:
                continue
            o = {
                'name': validator.name,
                'flags': flags,
                'hash': validator.hash,
            }
            h = combine_hashes_dict(o)
            # Don't actually store the somewhat useless validator hash.
            del o['hash']
            d[h] = o

        return d

    def validate_format(
        self,
        mode: validate.Mode,
        *,
        bar,
        constraints=None,
        warn_instead_of_error=False,
        args=None,  # TODO never used?
    ):

        check_constraints = constraints is not None
        match mode:
            case validate.Mode.INPUT:
                validators = self.problem.validators(
                    validate.InputValidator, check_constraints=check_constraints
                )
                expect_rejection = self.root == 'invalid_inputs'
            case validate.Mode.ANSWER:
                validators = self.problem.validators(
                    validate.AnswerValidator, check_constraints=check_constraints
                ) + self.problem.validators(
                    validate.OutputValidator, check_constraints=check_constraints
                )
                expect_rejection = self.root == 'invalid_answers'
            case validate.Mode.OUTPUT:
                raise NotImplementedError
            case _:
                raise ValueError

        validator_accepted = []
        for validator in validators:
            if type(validator) == validate.OutputValidator:
                args = ['case_sensitive', 'space_change_sensitive']
            flags = self.testdata_yaml_validator_flags(mode, validator)
            if flags is False:
                continue
            flags = args if flags is None else flags + args

            ret = validator.run(self, constraints=constraints, args=flags)
            if ret.ok is not True and ret.ok != config.RTV_WA:
                bar.log(f"Expected exit code {config.RTV_AC} or {config.RTV_WA}, got {ret.ok}")
                ret.ok = config.RTV_WA
            ok = ret.ok == True

            validator_accepted.append(ok)
            message = validator.name + (' accepted' if ok else ' rejected')

            # Print stdout and stderr whenever something is printed
            data = ''
            if not (ok or expect_rejection) or config.args.error:
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

                file = self.in_path if mode == validate.Mode.INPUT else self.ans_path
                data += (
                    f'{Style.RESET_ALL}-> {shorten_path(self.problem, file.parent) / file.name}\n'
                )
            else:
                data = ret.err

            bar.part_done(
                ok or expect_rejection,
                message,
                data=data,
                warn_instead_of_error=warn_instead_of_error,
            )

            if ok is True:
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
            elif mode == validate.Mode.INPUT and config.args.remove:
                bar.log(Fore.RED + 'REMOVING TESTCASE!' + Style.RESET_ALL)
                if self.in_path.exists():
                    self.in_path.unlink()
                if self.ans_path.exists():
                    self.ans_path.unlink()

            break

        if all(validator_accepted):
            if expect_rejection:
                success = False
                bar.error(f"{mode} validation (unexpectedly) succeeded")
            else:
                success = True
                validate.sanity_check(
                    self.in_path if mode == validate.Mode.INPUT else self.ans_path, bar
                )
        else:
            success = expect_rejection
        return success
