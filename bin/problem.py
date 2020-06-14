import re
import glob
import argparse
import hashlib

from pathlib import Path

import config
import program
import run
import validate
import shlex
from util import *


# A problem.
class Problem:
    _shortname_regex_string = '^[a-z0-9]+$'
    _shortname_regex = re.compile(_shortname_regex_string)

    def __init__(self, path, label=None):
        # The problem name/shortname, which is the name of the directory and used as a display name.
        self.name = path.resolve().name
        # The Path of the problem directory.
        self.path = path
        self.tmpdir = config.tmpdir / self.name
        # Read problem.yaml and domjudge-problem.ini into self.settings Namespace object.
        self._read_settings()

        # Some caches.
        self._testcases = dict()
        self._submissions = None
        self._validators = dict()
        self._programs = dict()
        self._program_callbacks = dict()

        # The label for the problem: A, B, A1, A2, X, ...
        if label is None:
            self.label = self.settings.probid
        else:
            self.label = label

        # TODO: transform this into nice warnings
        assert path.is_dir()
        if not Problem._shortname_regex.match(self.name):
            warn(
                f'Problem has a bad shortname: {self.name} does not match {self._shortname_regex_string}'
            )

    def _read_settings(self):
        # some defaults
        self.settings = {
            'timelimit': 1.0,
            'timeout': 3,
            'name': '',
            'validation': 'default',
            'validator_flags': [],
            'probid': 'A',
            'author': ''
        }

        # parse problem.yaml
        yamldata = read_yaml(self.path / 'problem.yaml')
        if yamldata:
            for k, v in yamldata.items():
                self.settings[k] = v

        # TODO: Get rid of domjudge-problem.ini; it's only remaining use is
        # timelimits.
        # parse domjudge-problem.ini
        domjudge_path = self.path / 'domjudge-problem.ini'
        if domjudge_path.is_file():
            for line in domjudge_path.read_text().splitlines():
                key, var = line.strip().split('=')
                var = var[1:-1]
                self.settings[key] = float(var) if key == 'timelimit' else var

        # Convert the dictionary to a namespace object.
        self.settings = argparse.Namespace(**self.settings)

        # Override settings by command line arguments.
        try:
            self.settings.timelimit = config.args.timelimit or self.settings.timelimit
        except AttributeError:
            pass

        timeout = 1.5 * self.settings.timelimit + 1
        try:
            if config.args.timeout:
                timeout = max(config.args.timeout, self.settings.timelimit + 1)
        except AttributeError:
            pass
        self.settings.timeout = int(timeout)

        if self.settings.validation not in config.VALIDATION_MODES:
            fatal(
                f'Unrecognised validation mode {self.settings.validation}. Must be one of {", ".join(config.VALIDATION_MODES)}'
            )

        if self.settings.validator_flags:
            self.settings.validator_flags = shlex.split(self.settings.validator_flags)

        self.interactive = self.settings.validation == 'custom interactive'

    def testcases(p, needans=True, only_sample=False, include_bad=False):
        samplesonly = only_sample
        try:
            if config.args.samples:
                sampleonly = True
        except AttributeError:
            pass

        if p.interactive: needans = False

        key = (needans, samplesonly)
        if key in p._testcases is not None: return p._testcases[key]

        in_paths = None
        # NOTE: Testcases must be specified relative to the problem root.
        if hasattr(config.args, 'testcases') and config.args.testcases:
            if samplesonly:
                warn(f'Ignoring the --samples flag because testcases are explicitly listed.')
            # Deduplicate testcases with both .in and .ans.
            in_paths = []
            for t in config.args.testcases:
                t = p.path / t
                if t.is_dir():
                    in_paths += glob(t, '**/*.in')
                else:
                    t = t.with_suffix('.in')
                    if not t.is_file(): warn(f'Testcase {t} not found.')
                    in_paths.append(t)

            in_paths = list(set(in_paths))
        else:
            in_paths = list(glob(p.path, 'data/sample/**/*.in'))
            if not samplesonly:
                in_paths += list(glob(p.path, 'data/secret/**/*.in'))
            if include_bad:
                in_paths += list(glob(p.path, 'data/bad/**/*.in'))

        testcases = []
        for f in in_paths:
            t = run.Testcase(p, f)
            # Require both in and ans files
            if needans and not t.ans_path.is_file():
                if not t.bad_input:
                    warn(f'Found input file {str(f)} without a .ans file. Skipping.')
                continue
            testcases.append(t)
        testcases.sort(key=lambda t: t.name)

        if len(testcases) == 0:
            warn(f'Didn\'t find any testcases for {p.name}')
            testcases = False

        p._testcases[key] = testcases
        return testcases

    # returns a map {expected verdict -> [(name, command)]}
    def submissions(problem):
        if problem._submissions is not None: return problem._submissions

        paths = []
        if hasattr(config.args, 'submissions') and config.args.submissions:
            for submission in config.args.submissions:
                if (problem.path / submission).parent == problem.path / 'submissions':
                    paths += glob(problem.path / submission, '*')
                else:
                    paths.append(problem.path / submission)
        else:
            for verdict in config.VERDICTS:
                paths += glob(problem.path / 'submissions' / verdict.lower(), '*')

        if len(paths) == 0:
            error('No submissions found!')
            problem._submissions = False
            return False

        programs = [run.Submission(problem, path) for path in paths]

        bar = ProgressBar('Build submissions', items=programs)

        for p in programs:
            bar.start(p)
            p.build(bar)
            bar.done()

        bar.finalize(print_done=False)

        # TODO: Clean these spurious newlines.
        if config.args.verbose:
            print()

        submissions = dict()
        for verdict in config.VERDICTS:
            submissions[verdict] = []

        # Filter out broken submissions.
        for p in programs:
            if p.ok:
                submissions[p.expected_verdict].append(p)

        problem._submissions = submissions
        return submissions

    # If check_constraints is True, this chooses the first validator that matches
    # contains 'constraints_file' in its source.
    # _validators maps from input/output to the list of validators.
    def validators(problem, validator_type, check_constraints=False):
        assert validator_type in ['input_format', 'output_format', 'output']

        # For custom validation, treat 'output' and 'output_format' validators the same.
        if problem.settings.validation != 'default' and validator_type == 'output':
            validator_type = 'output_format'

        if (validator_type, check_constraints) in problem._validators:
            return problem._validators[(validator_type, check_constraints)]

        # For default 'output' validation, use default_output_validator.py.
        if validator_type == 'output' and problem.settings.validation == 'default':
            validators = [
                validate.OutputValidator(problem,
                                         config.tools_root / 'bin' / 'default_output_validator.py')
            ]
            bar = ProgressBar('Build validators', items=validators)
            ok = True
            for p in validators:
                bar.start(p)
                ok &= p.build(bar)
                bar.done()
            bar.finalize(print_done=False)
            if not ok: validators = False
            problem._validators[validator_type] = validators
            return validators

        validator_dir = 'input' if validator_type == 'input_format' else 'output'

        paths = (glob(problem.path / (validator_dir + '_validators'), '*') +
                 glob(problem.path / (validator_dir + '_format_validators'), '*'))

        if len(paths) == 0:
            warn(f'No {validator_type} validators found.')
            problem._validators[validator_type] = False
            return False
        if validator_type == 'output_format' and problem.interactive and len(paths) > 1:
            error(
                f'Found more than one output validator, but validation type {problem.settings.validation} needs exactly one.'
            )
            problem._validators[validator_type] = False
            return False

        # TODO: Instead of checking file contents, maybe specify this in generators.yaml?
        def has_constraints_checking(f):
            try:
                return 'constraints_file' in f.read_text()
            except UnicodeDecodeError:
                return False

        if check_constraints:
            constraint_validators = []
            for f in paths:
                if f.is_file(): sources = [f]
                elif f.is_dir(): sources = glob(f, '**/*')
                has_constraints = False
                for s in sources:
                    if has_constraints_checking(s):
                        has_constraints = True
                        break
                if has_constraints:
                    constraint_validators.append(f)
            if len(constraint_validators) == 0:
                error('No {validator_type} constraint validators found: No matches for \'constraints_file\'.')
                return False

            paths = constraint_validators



        if validator_type == 'input_format':
            validators = [validate.InputValidator(problem, path, skip_double_build_warning=check_constraints) for path in paths]
        else:
            validators = [validate.OutputValidator(problem, path, skip_double_build_warning=check_constraints) for path in paths]

        bar = ProgressBar('Build validators', items=validators)

        ok = True
        for p in validators:
            bar.start(p)
            ok &= p.build(bar)
            bar.done()

        bar.finalize(print_done=False)

        # All validators must build.
        if not ok: validators = False

        # TODO: Clean these spurious newlines.
        if config.args.verbose:
            print()

        problem._validators[(validator_type, check_constraints)] = validators
        return validators

    def run_submissions(problem):
        needans = False if problem.interactive else True
        testcases = problem.testcases(needans=needans)

        if testcases is False:
            return False

        if problem.interactive:
            validators = problem.validators('output')
            if not validators: return False

        submissions = problem.submissions()
        if not submissions: return False

        max_submission_len = max([len(x.name) for cat in submissions for x in submissions[cat]])

        ok = True
        verdict_table = []
        for verdict in submissions:
            for submission in submissions[verdict]:
                d = dict()
                verdict_table.append(d)
                ok &= submission.run_all_testcases(max_submission_len, table_dict=d)

        if hasattr(config.args,'table') and config.args.table: Problem._print_table(verdict_table, testcases, submissions)

        return ok

    # Takes a list of submissions and runs them against the chosen testcases.
    # Instead of validating the output, this function just prints all output to the
    # terminal.
    # Note: The CLI only accepts one submission.
    def test_submissions(problem):
        submissions = problem.submissions()

        for verdict in submissions:
            for submission in submissions[verdict]:
                submission.test()
        return True

    @staticmethod
    def _print_table(verdict_table, testcases, submission):
        # Begin by aggregating bitstrings for all testcases, and find bitstrings occurring often (>=config.TABLE_THRESHOLD).
        def single_verdict(row, testcase):
            if testcase in row:
                if row[testcase.name]:
                    return cc.green + '1' + cc.reset
                else:
                    return cc.red + '0' + cc.reset
            else:
                return '-'

        make_verdict = lambda tc: ''.join(map(lambda row: single_verdict(row, tc), verdict_table))
        resultant_count, resultant_id = dict(), dict()
        special_id = 0
        for testcase in testcases:
            resultant = make_verdict(testcase)
            if resultant not in resultant_count:
                resultant_count[resultant] = 0
            resultant_count[resultant] += 1
            if resultant_count[resultant] == config.TABLE_THRESHOLD:
                special_id += 1
                resultant_id[resultant] = special_id

        scores = {}
        for t in testcases:
            scores[t] = 0
        for dct in verdict_table:
            failures = 0
            for t in dct:
                if not dct[t]:
                    failures += 1
            for t in dct:
                if not dct[t]:
                    scores[t] += 1. / failures
        scores_list = sorted(scores.values())

        print('\nVerdict analysis table. Submissions are ordered as above. Higher '
              'scores indicate they are critical to break some submissions.')
        for testcase in testcases:
            # Skip all AC testcases
            if all(map(lambda row: row[testcase.name], verdict_table)): continue

            color = cc.reset
            if len(scores_list) > 6 and scores[testcase.name] >= scores_list[-6]:
                color = cc.orange
            if len(scores_list) > 3 and scores[testcase.name] >= scores_list[-3]:
                color = cc.red
            print(f'{str(testcase.name):<60}', end=' ')
            resultant = make_verdict(testcase)
            print(resultant, end='  ')
            print(f'{color}{scores[testcase.name]:0.3f}{cc.reset}  ', end='')
            if resultant in resultant_id:
                print(str.format('(Type {})', resultant_id[resultant]), end='')
            print(end='\n')

    # Validate the format of the input or output files.
    # For input_format validation, also make sure all testcases are different.
    def validate_format(problem, validator_type, check_constraints=False):
        assert validator_type in ['input_format', 'output_format']

        if check_constraints:
            if not config.args.cpp_flags:
                config.args.cpp_flags = ''
            if not '-Duse_source_location' in config.args.cpp_flags:
                config.args.cpp_flags += ' -Duse_source_location'

            validators = problem.validators(validator_type, check_constraints=True)
        else:
            validators = problem.validators(validator_type)

        if problem.interactive and validator_type == 'output':
            log('Not validating .ans for interactive problem.')
            return True

        if not validators:
            return False

        testcases = problem.testcases(needans=validator_type == 'output_format', include_bad=True)

        if len(testcases) == 0:
            return True

        action = 'Validating ' + validator_type

        success = True

        constraints = {} if check_constraints else None

        hashes = {}

        # validate the testcases
        bar = ProgressBar(action, items=[t.name for t in testcases])
        for testcase in testcases:
            bar.start(testcase.name)

            if validator_type == 'input_format' and not testcase.included:
                data = testcase.in_path.read_text()
                h = hashlib.sha512(data.encode('utf-8')).hexdigest()
                if h in hashes:
                    ok = True
                    for t2 in hashes[h]:
                        if data == t2.in_path.read_text():
                            bar.error(f'Duplicate testcase: identical to {t2.name}')
                            ok = False
                            break

                    if ok:
                        hashes[h].append(testcase)
                    else:
                        continue
                else:
                    hashes[h] = [testcase]

            success &= testcase.validate_format(validator_type, bar=bar, constraints=constraints)
            bar.done()

        # Make sure all constraints are satisfied.
        if check_constraints:
            for loc, value in sorted(constraints.items()):
                loc = Path(loc).name
                has_low, has_high, vmin, vmax, low, high = value
                if not has_low:
                    warn(
                        f'BOUND NOT REACHED: The value at {loc} was never equal to the lower bound of {low}. Min value found: {vmin}'
                    )
                if not has_high:
                    warn(
                        f'BOUND NOT REACHED: The value at {loc} was never equal to the upper bound of {high}. Max value found: {vmax}'
                    )
                success = False

        if not config.args.verbose and success:
            print(ProgressBar.action(action, f'{cc.green}Done{cc.reset}'))
            if validator_type == 'output':
                print()
        else:
            print()

        return success
