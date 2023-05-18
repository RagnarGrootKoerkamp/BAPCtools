import re
import argparse
import hashlib
import random
import shlex
import sys

from pathlib import Path

import config
import parallel
import program
import run
import validate
from util import *
from colorama import Fore, Style


# A problem.
class Problem:
    _SHORTNAME_REGEX_STRING = '^[a-z0-9]+$'
    _SHORTNAME_REGEX = re.compile(_SHORTNAME_REGEX_STRING)

    def __init__(self, path, tmpdir, label=None):
        # The problem name/shortname, which is the name of the directory and used as a display name.
        self.name = path.resolve().name
        # The Path of the problem directory.
        self.path = path
        self.tmpdir = tmpdir / self.name
        # Read problem.yaml and domjudge-problem.ini into self.settings Namespace object.
        self._read_settings()

        # Some caches.
        self._testcases = dict()
        self._submissions = None
        self._validators = dict()
        self._programs = dict()
        self._program_callbacks = dict()
        # Dictionary from path to parsed file contents.
        self._testdata_yamls = dict()

        # The label for the problem: A, B, A1, A2, X, ...
        self.label = label

        # TODO: transform this into nice warnings
        assert path.is_dir()
        if not Problem._SHORTNAME_REGEX.match(self.name):
            warn(
                f'Problem has a bad shortname: {self.name} does not match {self._SHORTNAME_REGEX_STRING}'
            )

        self.statement_languages = self._determine_statement_languages()

    def _determine_statement_languages(self):
        """Determine the languages that are both mentioned in the problem.yaml under name
        and have a corresponding problem statement.

        If problem.yaml's name key is a string, convert into dict; assume `en` as default language.
        """
        if isinstance(self.settings.name, str):
            self.settings.name = {'en': self.settings.name}
        yamlnames = set(self.settings.name)
        texfiles = set(
            path.suffixes[0][1:]
            for path in glob(self.path, 'problem_statement/problem.*.tex')
        )
        for lang in texfiles - yamlnames:
            error(f"Found problem.{lang}.tex, but no corresponding name in problem.yaml.")
        for lang in yamlnames - texfiles:
            error(f"Found name for language {lang} in problem.yaml, but not problem.{lang}.tex.")
        return list(texfiles & yamlnames)

    def _read_settings(self):
        # some defaults
        self.settings = {
            'timelimit': 1.0,
            'timelimit_is_default': True,
            'timeout': 3,
            'name': '',
            'validation': 'default',
            'validator_flags': [],
            'author': '',
        }

        # parse problem.yaml
        if has_ryaml:
            try:
                yamldata = read_yaml_settings(self.path / 'problem.yaml')
            except ruamel.yaml.scanner.ScannerError:
                fatal('Make sure problem.yaml does not contain any more {% ... %}.')
        else:
            yamldata = read_yaml_settings(self.path / 'problem.yaml')

        if yamldata:
            for k, v in yamldata.items():
                self.settings[k] = v
            if 'timelimit' in yamldata:
                self.settings['timelimit_is_default'] = False

        # DEPRECATED: parse domjudge-problem.ini for the timelimit.
        domjudge_path = self.path / 'domjudge-problem.ini'
        if domjudge_path.is_file():
            verbose('domjudge-problem.ini is DEPRECATED. Use a .timelimit file instead.')
            for line in domjudge_path.read_text().splitlines():
                key, var = map(str.strip, line.strip().split('='))
                if (var[0] == '"' or var[0] == "'") and (var[-1] == '"' or var[-1] == "'"):
                    var = var[1:-1]
                if key == 'timelimit':
                    self.settings[key] = float(var)
                    self.settings['timelimit_is_default'] = False
                else:
                    self.settings[key] = var

        # Read the .timitlimit file if present.
        timelimit_path = self.path / '.timelimit'
        if timelimit_path.is_file():
            self.settings['timelimit'] = float(timelimit_path.read_text())
            self.settings['timelimit_is_default'] = False

        # Convert the dictionary to a namespace object.
        self.settings = argparse.Namespace(**self.settings)

        # Override settings by command line arguments.
        self.settings.timelimit = config.args.timelimit or self.settings.timelimit
        self.settings.timeout = int(config.args.timeout or 1.5 * self.settings.timelimit + 1)

        if self.settings.validation not in config.VALIDATION_MODES:
            fatal(
                f'Unrecognised validation mode {self.settings.validation}. Must be one of {", ".join(config.VALIDATION_MODES)}'
            )

        if isinstance(self.settings.validator_flags, str):
            self.settings.validator_flags = shlex.split(self.settings.validator_flags)

        self.interactive = self.settings.validation == 'custom interactive'

    # Walk up from absolute `path` (a file or directory) looking for the first testdata.yaml
    # file, and return its contents, or None if no testdata.yaml is found.
    def get_testdata_yaml(p, path):
        for dir in [path] + list(path.parents):
            f = dir / 'testdata.yaml'

            if f.is_file():
                # Store testdata.yaml files in a cache.
                if f not in p._testdata_yamls:
                    p._testdata_yamls[f] = read_yaml(f)
                return p._testdata_yamls[f]

            # Do not go above the data directory.
            if dir == p.path / 'data':
                break
        return None

    # statement_samples end in .in.statement and .ans.statement and are only used in the statement.
    def testcases(
        p, *, needans=True, needinteraction=False, only_sample=False, statement_samples=False, include_bad=False, copy=False,
    ):
        def maybe_copy(x):
            return x.copy() if copy and isinstance(x, (list, dict)) else x

        samplesonly = config.args.samples or only_sample

        if p.interactive:
            needans = False

        key = (needans, samplesonly, include_bad)
        if key in p._testcases is not None:
            return maybe_copy(p._testcases[key])

        in_paths = None
        if config.args.testcases:
            if samplesonly:
                assert False
            # Deduplicate testcases with both .in and .ans.
            in_paths = []
            for t in config.args.testcases:
                t = resolve_path_argument(p, t, 'data', suffixes=['.in'])
                if t:
                    # When running from contest level, the testcase must be inside the problem.
                    if config.level != 'problemset' or is_relative_to(problem.path, t):
                        if t.is_dir():
                            in_paths += glob(t, '**/*.in')
                        else:
                            in_paths.append(t)

            in_paths = list(set(in_paths))
        else:
            in_paths = list(glob(p.path, 'data/sample/**/*.in'))
            if statement_samples:
                in_paths += list(glob(p.path, 'data/sample/**/*.in.statement'))
            if not samplesonly:
                in_paths += list(glob(p.path, 'data/secret/**/*.in'))
            if include_bad:
                in_paths += list(glob(p.path, 'data/bad/**/*.in'))

        testcases = []
        for f in in_paths:
            t = run.Testcase(p, f)
            # Require both in and ans files
            if needinteraction and not t.in_path.with_suffix('.interaction').is_file():
                assert only_sample
                warn(f'Found input file {f} without a .interaction file. Skipping.')
                continue
            if needans and not t.ans_path.is_file():
                if not t.bad_input:
                    warn(f'Found input file {f} without a .ans file. Skipping.')
                continue
            testcases.append(t)
        testcases.sort(key=lambda t: t.name)

        if len(testcases) == 0:
            if needinteraction:
                warn(f'Didn\'t find any testcases with interaction for {p.name}')
            else:
                warn(f'Didn\'t find any testcases{" with answer" if needans else ""} for {p.name}')
            testcases = False

        p._testcases[key] = testcases
        return maybe_copy(testcases)

    # returns a map {expected verdict -> [(name, command)]}
    def submissions(problem, accepted_only=False, copy=False):
        def maybe_copy(x):
            return x.copy() if copy and isinstance(x, (list, dict)) else x

        if problem._submissions is not None:
            return maybe_copy(problem._submissions.copy())

        paths = []
        if config.args.submissions:
            if accepted_only:
                accepted_only = 'all'

            def add(s):
                if s in paths:
                    warn(f'Ignoring duplicate submission: {s}')
                    return
                paths.append(s)

            for submission in config.args.submissions:
                s = resolve_path_argument(problem, submission, 'submissions')
                if s:
                    if s == problem.path / 'submissions':
                        paths += glob(s, '*/*')
                    elif s.parent == problem.path / 'submissions':
                        for s in glob(s, '*'):
                            add(s)
                    else:
                        # If running from a contest, the submission must be inside a problem.
                        if config.level == 'problem' or is_relative_to(problem.path, s):
                            add(s)
        else:
            for s in glob(problem.path / 'submissions', ('accepted/*' if accepted_only else '*/*')):
                if (
                    s.parent.name == 'time_limit_exceeded'
                    and config.RUNNING_TEST
                    and not config.TEST_TLE_SUBMISSIONS
                ):
                    continue

                paths.append(s)

        if len(paths) == 0:
            error('No submissions found!')
            problem._submissions = False
            return False

        programs = [run.Submission(problem, path) for path in paths]

        bar = ProgressBar('Build submissions', items=programs)

        def build_program(p):
            localbar = bar.start(p)
            p.build(localbar)
            localbar.done()

        p = parallel.Parallel(build_program)
        for pr in programs:
            p.put(pr)
        p.done()

        bar.finalize(print_done=False)

        submissions = dict()
        for verdict in config.VERDICTS:
            submissions[verdict] = []

        # Filter out broken submissions.
        for p in programs:
            if p.ok:
                submissions[p.expected_verdicts[0]].append(p)

        if sum(len(submissions[x]) for x in submissions) == 0:
            submissions = False
        problem._submissions = submissions
        if accepted_only == 'all':
            subs = []
            for x in submissions:
                subs += submissions[x]
            return subs
        if accepted_only:
            return maybe_copy(submissions['ACCEPTED'])
        return maybe_copy(submissions)

    # If check_constraints is True, this chooses the first validator that matches
    # contains 'constraints_file' in its source.
    # _validators maps from input/output to the list of validators.
    def validators(problem, validator_type, check_constraints=False):
        assert validator_type in ['input_format', 'output_format', 'output']

        # For custom validation, treat 'output' and 'output_format' validators the same.
        if problem.settings.validation != 'default' and validator_type == 'output_format':
            validator_type = 'output'

        key = (validator_type, check_constraints)
        if key in problem._validators:
            return problem._validators[key]

        # For default 'output' validation, use default_output_validator.cpp.
        if validator_type == 'output' and problem.settings.validation == 'default':
            validators = [
                validate.OutputValidator(
                    problem, config.tools_root / 'support' / 'default_output_validator.cpp'
                )
            ]
            bar = ProgressBar(f'Build {validator_type} validators', items=validators)
            ok = True
            for p in validators:
                bar.start(p)
                ok &= p.build(bar)
                bar.done()
            bar.finalize(print_done=False)
            if not ok:
                validators = False
            problem._validators[key] = validators
            return validators

        validator_dir = 'input' if validator_type == 'input_format' else 'output'

        paths = glob(problem.path / (validator_dir + '_validators'), '*') + glob(
            problem.path / (validator_dir + '_format_validators'), '*'
        )

        if len(paths) == 0:
            # Only log/warn missing validators in generate mode.
            if config.args.action == 'generate':
                if validator_type == 'output_format':
                    log(f'No {validator_type} validators found.')
                else:
                    warn(f'No {validator_type} validators found.')
                    problem._validators[key] = False
                    return False
        if validator_type == 'output' and problem.interactive and len(paths) != 1:
            error(
                f'Found {len(paths)} output validators, but validation type {problem.settings.validation} needs exactly one.'
            )
            problem._validators[key] = False
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
                if f.is_file():
                    sources = [f]
                elif f.is_dir():
                    sources = glob(f, '**/*')
                has_constraints = False
                for s in sources:
                    if has_constraints_checking(s):
                        has_constraints = True
                        break
                if has_constraints:
                    constraint_validators.append(f)
            if len(constraint_validators) == 0:
                error(
                    f'No {validator_type} constraint validators found: No matches for \'constraints_file\'.'
                )
                return False

            paths = constraint_validators

        if validator_type == 'input_format':
            validators = [
                validate.InputValidator(
                    problem,
                    path,
                    skip_double_build_warning=check_constraints,
                    check_constraints=check_constraints,
                )
                for path in paths
            ]
        else:
            validators = [
                validate.OutputValidator(
                    problem,
                    path,
                    skip_double_build_warning=check_constraints,
                    check_constraints=check_constraints,
                )
                for path in paths
            ]

        bar = ProgressBar(f'Build {validator_type} validators', items=validators)
        ok = True

        def build_program(p):
            nonlocal ok
            localbar = bar.start(p)
            ok &= p.build(localbar)
            localbar.done()

        p = parallel.Parallel(build_program)
        for pr in validators:
            p.put(pr)
        p.done()

        bar.finalize(print_done=False)

        # All validators must build.
        if not ok:
            validators = False

        problem._validators[key] = validators
        return validators

    def run_submissions(problem):
        needans = False if problem.interactive else True
        testcases = problem.testcases(needans=needans)

        if testcases is False:
            return False

        if problem.interactive:
            validators = problem.validators('output')
            if not validators:
                return False

        submissions = problem.submissions()
        if not submissions:
            return False

        max_submission_len = max([len(x.name) for cat in submissions for x in submissions[cat]])

        # Pre build all output validators to prevent nested ProgressBars.
        if problem.validators('output') is False:
            return False

        ok = True
        verdict_table = []
        # When true, the ProgressBar will print a newline before the first error log.
        needs_leading_newline = False if config.args.verbose else True
        for verdict in submissions:
            for submission in submissions[verdict]:
                d = dict()
                verdict_table.append(d)
                submission_ok, printed_newline = submission.run_all_testcases(
                    max_submission_len, table_dict=d, needs_leading_newline=needs_leading_newline
                )
                needs_leading_newline = not printed_newline
                ok &= submission_ok

        if config.args.table:
            Problem._print_table(verdict_table, testcases, submissions)

        return ok

    # Takes a list of submissions and runs them against the chosen testcases.
    # Instead of validating the output, this function just prints all output to the
    # terminal.
    # Note: The CLI only accepts one submission.
    def test_submissions(problem):
        submissions = problem.submissions()
        if submissions is False:
            return False

        for verdict in submissions:
            for submission in submissions[verdict]:
                if config.args.interactive:
                    submission.test_interactive()
                else:
                    submission.test()
        return True

    @staticmethod
    def _print_table(verdict_table, testcases, submission):
        # Begin by aggregating bitstrings for all testcases, and find bitstrings occurring often (>=config.TABLE_THRESHOLD).
        def single_verdict(row, testcase):
            if testcase.name in row:
                if row[testcase.name]:
                    return Fore.GREEN + '1' + Style.RESET_ALL
                else:
                    return Fore.RED + '0' + Style.RESET_ALL
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
            scores[t.name] = 0
        for dct in verdict_table:
            failures = 0
            for t in dct:
                if not dct[t]:
                    failures += 1
            for t in dct:
                if not dct[t]:
                    scores[t] += 1.0 / failures
        scores_list = sorted(scores.values())

        print(
            '\nVerdict analysis table. Submissions are ordered per column as above. Higher '
            'scores indicate they are critical to break some submissions. Only cases breaking at least one submission are listed.',
            file=sys.stderr,
        )
        print(f'{Fore.RED}0{Style.RESET_ALL}: submission fails testcase', file=sys.stderr)
        print(f'{Fore.GREEN}1{Style.RESET_ALL}: submission passes testcase\n', file=sys.stderr)

        for testcase in testcases:
            # Skip all AC testcases
            if all(map(lambda row: testcase.name in row and row[testcase.name], verdict_table)):
                continue

            color = Style.RESET_ALL
            if len(scores_list) > 6 and scores[testcase.name] >= scores_list[-6]:
                color = Fore.YELLOW
            if len(scores_list) > 3 and scores[testcase.name] >= scores_list[-3]:
                color = Fore.RED
            print(f'{str(testcase.name):<60}', end=' ', file=sys.stderr)
            resultant = make_verdict(testcase)
            print(resultant, end='  ', file=sys.stderr)
            print(
                f'{color}{scores[testcase.name]:0.3f}{Style.RESET_ALL}  ', end='', file=sys.stderr
            )
            if resultant in resultant_id:
                print(str.format('(Type {})', resultant_id[resultant]), end='', file=sys.stderr)
            print(end='\n', file=sys.stderr)

    def reset_testcase_hashes(self):
        self._testcase_hashes = {}

    # Returns None for new testcases or the Testcase object it equals.
    def matches_existing_testcase(self, t):
        if t.bad_input or t.bad_output:
            return None
        d = t.in_path.read_text()
        if d in self._testcase_hashes:
            return self._testcase_hashes[d]
        self._testcase_hashes[d] = t
        return None

    # Validate the format of the input or output files.
    # For input_format validation, also make sure all testcases are different.
    # Constraints is None/True/dictionary. When dictionary, contraints will be stored there.
    def validate_format(problem, validator_type, constraints=None):
        if constraints is True:
            constraints = {}
        assert constraints is None or isinstance(constraints, dict)
        assert validator_type in ['input_format', 'output_format']

        validators = problem.validators(validator_type, check_constraints=constraints is not None)

        if problem.interactive and validator_type == 'output_format':
            log('Not validating .ans for interactive problem.')
            return True

        if validators is False:
            return False

        testcases = problem.testcases(needans=validator_type == 'output_format', include_bad=True)

        if testcases is False:
            return True

        if len(testcases) == 0:
            return True

        action = 'Validating ' + validator_type

        success = True

        problem.reset_testcase_hashes()

        # validate the testcases
        bar = ProgressBar(action, items=[t.name for t in testcases])
        for testcase in testcases:
            bar.start(testcase.name)

            if validator_type == 'input_format' and not testcase.included:
                t2 = problem.matches_existing_testcase(testcase)
                if t2 is not None:
                    bar.error(f'Duplicate testcase: identical to {t2.name}')
                    ok = False
                    continue

            success &= testcase.validate_format(validator_type, bar=bar, constraints=constraints)
            bar.done()

        bar.finalize(print_done=True)

        # Make sure all constraints are satisfied.
        if constraints:
            for loc, value in sorted(constraints.items()):
                loc = Path(loc).name
                name, has_low, has_high, vmin, vmax, low, high = value
                if not has_low:
                    warn(
                        f'BOUND NOT REACHED: The value of `{name}` at {loc} was never equal to the lower bound of {low}. Min value found: {vmin}'
                    )
                if not has_high:
                    warn(
                        f'BOUND NOT REACHED: The value of `{name}` at {loc} was never equal to the upper bound of {high}. Max value found: {vmax}'
                    )
                success = False

        return success

    # Return absolute path to default submission, starting from the submissions directory.
    # This function will always raise a warning.
    # Which submission is used is implementation defined, unless one is explicitly given on the command line.
    def default_solution_path(problem):
        if config.args.default_solution:
            fixed = True
            solution = problem.path / config.args.default_solution
        else:
            fixed = False
            # Use one of the accepted submissions.
            solutions = list(glob(problem.path, 'submissions/accepted/*'))
            if len(solutions) == 0:
                fatal(f'No solution specified and no accepted submissions found.')
                return False

            # Note: we explicitly random shuffle the submission that's used to generate answers to
            # encourage setting it in generators.yaml.
            solution = random.choice(solutions)
        solution_short_path = solution.relative_to(problem.path / 'submissions')

        # Only show these warning when generate was called.
        # For normal 'run' output this isn't important enough.
        if config.args.action == 'generate':
            if fixed:
                log(
                    f'''Prefer setting the solution in generators/generators.yaml:
      > solution: /{solution.relative_to(problem.path)}'''
                )
            else:
                warn(
                    f'''No solution specified. Using randomly chosen {solution_short_path} instead.
      Use `generate --default_solution` to use a fixed solution.'''
                )

        return Path('/') / solution.relative_to(problem.path)
