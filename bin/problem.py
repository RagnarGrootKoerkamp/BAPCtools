import re
import glob
import argparse

from pathlib import Path

import config
import program
import run
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

    # TODO: This should be overridden by command line flags.
    def _read_settings(self):
        # some defaults
        self.settings = {
            'timelimit': 1.0,
            'timeout': 3,
            'name': '',
            'validation': 'default',
            'validator_flags': [],
            'probid': 'A',
        }

        # parse problem.yaml
        yamlpath = self.path / 'problem.yaml'
        yamldata = read_yaml(yamlpath / 'problem.yaml')
        if yamldata:
            for k, v in yamldata.items():
                self.settings[k] = v

        # TODO: Get rid of domjudge-problem.ini; it's only remaining use is
        # timelimits.
        # parse domjudge-problem.ini
        domjudge_path = self.path / 'domjudge-problem.ini'
        if domjudge_path.is_file():
            for line in domjudge_path.read_text():
                key, var = line.strip().split('=')
                var = var[1:-1]
                self.settings[key] = float(var) if key == 'timelimit' else var

        # Convert the dictionary to a namespace object.
        self.settings = argparse.Namespace(**self.settings)

        # Override settings by command line arguments.
        self.settings.timelimit = config.arg('timelimit', self.settings.timelimit)

        timeout = 1.5 * self.settings.timelimit + 1
        if config.arg('timeout'): timeout = max(config.arg('timeout'), self.settings.timelimit+1)
        self.settings.timeout = int(timeout)

        if self.settings.validation not in config.VALIDATION_MODES:
            fatal(f'Unrecognised validation mode {self.settings.validation}. Must be one of {", ".join(config.VALIDATION_MODES)}')

        if self.settings.validator_flags:
            self.settings.validator_flags = shlex.split(self.settings.validator_flags)

    def testcases(p, needans=True, only_sample=False):
        samplesonly = only_sample or config.arg('samples', False)

        key = (needans, samplesonly)
        if key in p._testcases is not None: return p._testcases[key]

        in_paths = None
        # NOTE: Testcases must be specified relative to the problem root.
        if config.arg('testcases'):
            if samplesonly:
                warn(f'Ignoring the --samples flag because testcases are explicitly listed.')
            # Deduplicate testcases with both .in and .ans.
            in_paths = []
            for t in config.args.testcases:
                if Path(p.path / t).is_dir():
                    in_paths += glob(p.path / t, '**/*.in')
                else:
                    t = t.with_suffix('.in')
                    if not t.is_path(): warn(f'Testcase {t} not found.')
                    in_paths.append(p.path / t)

            in_paths = list(set(in_paths))
        else:
            in_paths = list(glob(p.path, 'data/sample/**/*.in'))
            if not samplesonly:
                in_paths += list(glob(p.path, 'data/secret/**/*.in'))

        testcases = []
        for f in in_paths:
            # Require both in and ans files
            if needans and not f.with_suffix('.ans').is_file():
                warn(f'Found input file {str(f)} without a .ans file. Skipping.')
                continue
            testcases.append(run.Testcase(p, f))
        testcases.sort(key = lambda t: t.name)

        if len(testcases) == 0:
            warn(f'Didn\'t find any testcases for {p.name}')
            testcases = False

        p._testcases[key] = testcases
        return testcases


    # returns a map {expected verdict -> [(name, command)]}
    def submissions(problem):
        if problem._submissions is not None: return problem._submissions

        paths = []
        if config.arg('submissions'):
            for submission in config.arg('submissions'):
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
        if config.verbose:
            print()

        submissions = dict()
        for verdict in config.VERDICTS: submissions[verdict] = []

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
        if not check_constraints and validator_type in problem._validators:
            return problem._validators[validator_type]

        paths = (glob(problem.path / (validator_type + '_validators'), '*') +
                 glob(problem.path / (validator_type + '_format_validators'), '*'))

        if len(paths) == 0:
            error(f'No {validator_type} validators found.')
            problem._validators[validator_type] = False
            return False
        if problem.settings.validation == 'custom interactive' and len(paths) > 1:
            error(f'Found more than one output validator, but validation type {problem.settings.validation} needs exactly one.')
            problem._validators[validator_type] = False
            return False

        # TODO: Instead of checking file contents, maybe specify this in generators.yaml?
        def has_constraints_checking(f):
            return 'constraints_file' in f.read_text()

        if check_constraints:
            for f in paths:
                if f.is_file(): sources = [f]
                elif f.is_dir(): sources = glob(f, '**/*')
                has_constraints = False
                for s in sources:
                    if has_constraints_checking(s):
                        has_constraints = True
                        break
                if has_constraints:
                    files = [f]
                    break

        validators = [program.Validator(problem, path) for path in paths]
        bar = ProgressBar('Build validators', items=validators)

        ok = True
        for p in validators:
            bar.start(p)
            ok &= p.build(bar)
            bar.done()

        bar.finalize(print_done=False)

        # All validators must build.
        if not ok: return False

        # TODO: Clean these spurious newlines.
        if config.verbose:
            print()

        if not check_constraints:
            problem._validators[validator_type] = validators
        return validators


    def run_submissions(problem):
        needans = False if problem.settings.validation == 'custom interactive' else True
        testcases = problem.testcases(needans=needans)

        if len(testcases) == 0:
            return False

        if problem.settings.validation in ['custom', 'custom interactive']:
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

        if config.arg('table'): Problem._print_table(verdict_table, testcases, submissions)

        return ok

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

