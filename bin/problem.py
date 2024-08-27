import re
import argparse
import shlex
import sys
import threading

from pathlib import Path
from typing import Callable, Literal, Optional, Type, TYPE_CHECKING

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from program import Program

import config
import latex
import parallel
import run
import testcase
import validate
import verdicts
from util import *
from colorama import Fore, Style


# A problem.
class Problem:
    _SHORTNAME_REGEX_STRING = '^[a-z0-9]+$'
    _SHORTNAME_REGEX = re.compile(_SHORTNAME_REGEX_STRING)

    def __init__(self, path: Path, tmpdir: Path, label: Optional[str] = None):
        # The problem name/shortname, which is the name of the directory and used as a display name.
        self.name = path.resolve().name
        # The Path of the problem directory.
        self.path = path
        self.tmpdir: Path = tmpdir / self.name
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        # Read problem.yaml and domjudge-problem.ini into self.settings Namespace object.
        self._read_settings()

        # Some caches.
        self._testcases = dict[
            tuple[Optional[validate.Mode], bool, bool], list[testcase.Testcase]
        ]()
        self._submissions: Optional[
            dict[verdicts.Verdict, list[run.Submission]] | Literal[False]
        ] = None
        self._validators_cache = dict[  # The "bool" is for "check_constraints"
            tuple[Type[validate.AnyValidator], bool], list[validate.AnyValidator]
        ]()
        self._programs = dict[Path, "Program"]()
        self._program_callbacks = dict[Path, list[Callable[["Program"], None]]]()
        # Dictionary from path to parsed file contents.
        self._testdata_yamls = dict[Path, dict[str, Any]]()  # TODO Add type for testdata.yaml
        self._testdata_lock = threading.Lock()

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
        yamllangs = set(self.settings.name)
        texlangs = set(
            path.suffixes[0][1:] for path in glob(self.path, 'problem_statement/problem.*.tex')
        )
        for lang in texlangs - yamllangs:
            error(
                f"{self.name}: Found problem.{lang}.tex, but no corresponding name in problem.yaml."
            )
        for lang in yamllangs - texlangs:
            error(
                f"{self.name}: Found name for language {lang} in problem.yaml, but not problem.{lang}.tex."
            )
        # Check that names in problem.yaml and \problemname{} in problem.*.tex agree:
        for lang in texlangs & yamllangs:
            unnormalised_yamlname = self.settings.name[lang]
            yamlname = ' '.join(unnormalised_yamlname.split())
            with open(self.path / 'problem_statement' / f'problem.{lang}.tex') as texfile:
                match texname := latex.get_argument_for_command(texfile, 'problemname'):
                    case None:
                        error(rf"No \problemname found in problem.{lang}.tex")
                        continue
                    case '':
                        continue
                    case r'\problemyamlname':
                        warn(
                            rf"Prefer using \problemname{{}} instead of \problemname{{\problemyamlname}} in problem.{lang}.tex"
                        )
                        continue
                    case s if '\\' in s or '_' in s or '^' in s:
                        # texname contains markup, like "CO_2" or "\emph{Hello}":
                        # Assume authors know what they're doing
                        continue
                    case s if s != yamlname:
                        warn(
                            f'Problem titles in problem.{lang}.tex ({texname})'
                            + f' and problem.yaml ({yamlname}) differ;'
                            + r' consider using \problemname{}.'
                        )
        return sorted(texlangs & yamllangs)

    def _read_settings(self):
        # some defaults
        settings = {
            'timelimit': 1.0,
            'timelimit_is_default': True,
            'timeout': 3,
            'name': '',
            'validation': 'default',
            'validator_flags': [],
            'author': '',
            'uuid': None,
            'limits': {},
        }

        yaml_path = self.path / 'problem.yaml'

        # parse problem.yaml
        if has_ryaml:
            try:
                yamldata = read_yaml_settings(yaml_path)
            except ruamel.yaml.scanner.ScannerError:
                fatal('Make sure problem.yaml does not contain any more {% ... %}.')
        else:
            yamldata = read_yaml_settings(yaml_path)

        if yamldata:
            for k, v in yamldata.items():
                settings[k] = v
            if 'timelimit' in yamldata:
                settings['timelimit_is_default'] = False

        # DEPRECATED: parse domjudge-problem.ini for the timelimit.
        domjudge_path = self.path / 'domjudge-problem.ini'
        if domjudge_path.is_file():
            verbose('domjudge-problem.ini is DEPRECATED. Use a .timelimit file instead.')
            for line in domjudge_path.read_text().splitlines():
                key, var = map(str.strip, line.strip().split('='))
                if (var[0] == '"' or var[0] == "'") and (var[-1] == '"' or var[-1] == "'"):
                    var = var[1:-1]
                if key == 'timelimit':
                    settings[key] = float(var)
                    settings['timelimit_is_default'] = False
                else:
                    settings[key] = var

        # Read the .timitlimit file if present.
        timelimit_path = self.path / '.timelimit'
        if timelimit_path.is_file():
            settings['timelimit'] = float(timelimit_path.read_text())
            settings['timelimit_is_default'] = False

        # Convert the dictionary to a namespace object.
        self.settings = argparse.Namespace(**settings)

        # Override settings by command line arguments.
        self.settings.timelimit = config.args.timelimit or self.settings.timelimit
        self.settings.timeout = int(config.args.timeout or 1.5 * self.settings.timelimit + 1)

        mode = parse_validation(self.settings.validation)
        self.interactive = mode['interactive']
        self.multipass = mode['multi-pass']

        if isinstance(self.settings.validator_flags, str):
            self.settings.validator_flags = shlex.split(self.settings.validator_flags)

        if self.settings.uuid == None:
            self.settings.uuid = generate_problem_uuid()
            raw = yaml_path.read_text().rstrip()
            raw += f'\n# uuid added by BAPCtools\nuuid: {self.settings.uuid}\n'
            yaml_path.write_text(raw)
            log(f'Generated UUID for {self.name}, added to problem.yaml')

        # TODO: implement other limits
        # TODO move timelimit to this?
        limits = self.settings.limits.copy()

        has_validation_passes = 'validation_passes' in limits
        if self.multipass and not has_validation_passes:
            limits['validation_passes'] = 2
        if not self.multipass and has_validation_passes:
            limits.pop('validation_passes')
            warn('limit: validation_passes is only used for multipass problems. SKIPPED.')

        self.limits = argparse.Namespace(**limits)  # TODO #102 typed Namespace?

    def _parse_testdata_yaml(p, path, bar):
        assert path.is_relative_to(p.path / 'data')
        for dir in [path] + list(path.parents):
            # Do not go above the data directory.
            if dir == p.path:
                return

            f = dir / 'testdata.yaml'
            if not f.is_file() or f in p._testdata_yamls:
                continue
            with p._testdata_lock:
                if not f in p._testdata_yamls:
                    p._testdata_yamls[f] = flags = read_yaml(f, plain=True)

                    # verify testdata.yaml
                    for k in flags:
                        match k:
                            case 'output_validator_flags':
                                if not isinstance(flags[k], str):
                                    bar.error(
                                        "ouput_validator_flags must be string",
                                        resume=True,
                                        print_item=False,
                                    )
                            case 'input_validator_flags':
                                if not isinstance(flags[k], (str, dict)):
                                    bar.error(
                                        "input_validator_flags must be string or map",
                                        resume=True,
                                        print_item=False,
                                    )
                                if isinstance(flags[k], dict):
                                    input_validator_names = set(
                                        val.name for val in p.validators(validate.InputValidator)
                                    )
                                    for name in set(flags[k]) - input_validator_names:
                                        bar.warn(
                                            f'Unknown input validator {name}; expected {input_validator_names}',
                                            print_item=False,
                                        )
                            case 'grading' | 'run_samples':
                                bar.warn(f'{k} not implemented in BAPCtools', print_item=False)
                            case _:
                                path = f.relative_to(p.path / 'data')
                                bar.warn(f'Unknown key "{k}" in {path}', print_item=False)
            # Do not go above the data directory.
            if dir == p.path / 'data':
                break

    def get_testdata_yaml(p, path, key, bar, name=None) -> str | None:
        """
        Find the testdata flags applying at the given path for the given key.
        If necessary, walk up from `path` looking for the first testdata.yaml file that applies,

        Side effects: parses and caches the file.

        Arguments
        ---------
        path: absolute path (a file or a directory)
        key: The testdata.yaml key to look for, either of 'input_validator_flags', 'output_validator_flags', or 'grading'.
            'grading' is not implemented
        name: If key == 'input_validator_flags', optionally the name of the input validator

        Returns:
        --------
        string or None if no testdata.yaml is found.
        TODO: when 'grading' is supported, it also can return dict
        """
        if key not in ['input_validator_flags', 'output_validator_flags']:
            raise NotImplementedError(key)
        if key != 'input_validator_flags' and name is not None:
            raise ValueError(
                f"Only input validators support flags by validator name, got {key} and {name}"
            )

        # parse and cache testdata.yaml
        p._parse_testdata_yaml(path, bar)

        # extract the flags
        for dir in [path] + list(path.parents):
            # Do not go above the data directory.
            if dir == p.path:
                return None

            f = dir / 'testdata.yaml'
            if f not in p._testdata_yamls:
                continue
            flags = p._testdata_yamls[f]
            if key in flags:
                if key == 'output_validator_flags':
                    if not isinstance(flags[key], str):
                        bar.error("ouput_validator_flags must be string")
                    return flags[key]

                if key == 'input_validator_flags':
                    if not isinstance(flags[key], (str, dict)):
                        bar.error("input_validator_flags must be string or map")
                    if isinstance(flags[key], str):
                        return flags[key]
                    elif name in flags[key]:
                        return flags[key][name]

        return None

    def testcases(
        p,
        *,
        mode: Optional[validate.Mode] = None,
        needans=True,
        only_samples=False,
    ) -> list[testcase.Testcase]:
        only_samples = config.args.samples or only_samples

        key = (mode, needans, only_samples)
        if key in p._testcases is not None:
            return p._testcases[key]

        in_paths = None
        if config.args.testcases:
            if only_samples:
                assert False
            # Deduplicate testcases with both .in and .ans.
            in_paths = []
            for t in config.args.testcases:
                t = resolve_path_argument(p, t, 'data', suffixes=['.in'])
                if t:
                    # When running from contest level, the testcase must be inside the problem.
                    if config.level != 'problemset' or is_relative_to(p.path, t):
                        if t.is_dir():
                            in_paths += glob(t, '**/*.in')
                        else:
                            in_paths.append(t)

            in_paths = list(set(in_paths))
        elif mode is not None:
            in_paths = []
            for prefix in {
                validate.Mode.INPUT: ['secret', 'sample'],
                validate.Mode.ANSWER: ['secret', 'sample'],
                validate.Mode.INVALID: config.INVALID_CASE_DIRECTORIES,
            }[mode]:
                in_paths += glob(p.path, f'data/{prefix}/**/*.in')
        else:
            in_paths = list(glob(p.path, 'data/sample/**/*.in'))
            if not only_samples:
                in_paths += list(glob(p.path, 'data/secret/**/*.in'))

        testcases = []
        for f in in_paths:
            t = testcase.Testcase(p, f, print_warn=True)
            if (
                (p.interactive or p.multipass)
                and mode == validate.Mode.INVALID
                and t.root in ['invalid_answers', 'invalid_outputs']
            ):
                msg = ''
                if p.interactive:
                    msg += ' interactive'
                if p.multipass:
                    msg += ' multi-pass'
                warn(f'Found file {f} for {mode} validation in{msg} problem. Skipping.')
                continue
            if needans and not t.ans_path.is_file():
                if t.root != 'invalid_inputs':
                    warn(f'Found input file {f} without a .ans file. Skipping.')
                    continue
            testcases.append(t)
        testcases.sort(key=lambda t: t.name)

        if len(testcases) == 0:
            ans = ' with answer' if needans and mode != validate.Mode.INVALID else ''
            val = f' for {mode} validation' if mode is not None else ''
            # TODO perhaps move this log to the use site?
            (log if mode == validate.Mode.INVALID else warn)(
                f'Didn\'t find any testcases{ans}{val} in problem {p.name}. Skipping.'
            )

        p._testcases[key] = testcases
        return testcases

    # Returns a list of:
    # - (Path, Path): (.in, .ans) pair
    # - (Path, Path): (.in.statement, .ans.statement) pair
    # -  Path       :  .interaction file
    def statement_samples(p) -> list[Path | tuple[Path, Path]]:
        statement_in_paths = list(glob(p.path, 'data/sample/**/*.in.statement'))
        interaction_paths = list(glob(p.path, 'data/sample/**/*.interaction'))

        # Make sure that .in.statement files are not mixed with .interaction files.
        for in_path in interaction_paths:
            if in_path.with_suffix('.in.statement').is_file():
                warn(
                    f'Do not mix .in.statement files and .interaction files with the same basename in {p}.'
                )

        # A .in may be shadowed by either .in.statement or .interaction, in which case the .in itself is not shown in the PDF.
        in_paths = []
        for in_path in list(glob(p.path, 'data/sample/**/*.in')):
            if in_path.with_suffix('.in.statement').is_file():
                continue
            if in_path.with_suffix('.interaction').is_file():
                continue
            in_paths.append(in_path)

        # .interaction files cannot be mixed with .in/.ans pairs.
        if len(interaction_paths) != 0 and len(in_paths) + len(statement_in_paths) != 0:
            warn(f'Do not mix .interaction files with .in/.ans files in {p}.')

        # Non-interactive and Non-multi-pass problems should not have .interaction files.
        # On the other hand, interactive problems are allowed to have .{in,ans}.statement files,
        # so that they can emulate a non-interactive problem with on-the-fly generated input.
        if not p.interactive and not p.multipass:
            if len(interaction_paths) != 0:
                warn(
                    f'Non-interactive/Non-multi-pass problem {p.name} should not have data/sample/*.interaction files.'
                )
            interaction_paths = []

        testcases = list[Path | tuple[Path, Path]]()
        for in_path in in_paths:
            ans_path = in_path.with_suffix('.ans')
            if not ans_path.is_file():
                warn(f'Found input file {in_path} without a .ans file. Skipping.')
                continue
            testcases.append((in_path, ans_path))

        for in_path in statement_in_paths:
            # first remove .statement, then replace .in with .ans.statement
            ans_path = in_path.with_suffix('').with_suffix('.ans.statement')
            if not ans_path.is_file():
                warn(f'Found input file {in_path} without a .ans.statement file. Skipping.')
                continue
            testcases.append((in_path, ans_path))

        for interaction_path in interaction_paths:
            testcases.append(interaction_path)

        testcases.sort()

        return testcases

    # Returns the list of submissions passed as command-line arguments, or the list of accepted submissions by default.
    def selected_or_accepted_submissions(problem) -> list["run.Submission"]:
        submissions = problem.submissions()
        if not submissions:
            return []
        if config.args.submissions:
            return sum(submissions.values(), [])
        else:
            return submissions[verdicts.Verdict.ACCEPTED]

    def submissions(problem) -> dict[verdicts.Verdict, list["run.Submission"]] | Literal[False]:

        if problem._submissions:
            return {verdict: subs.copy() for verdict, subs in problem._submissions.items()}

        paths = []
        if config.args.submissions:

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
            for s in glob(problem.path / 'submissions', '*/*'):
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

        parallel.run_tasks(build_program, programs)

        bar.finalize(print_done=False)

        submissions = dict[verdicts.Verdict, list[run.Submission]]()
        for verdict in verdicts.VERDICTS:
            submissions[verdict] = []

        # Filter out broken submissions.
        for p in programs:
            if p.ok:
                submissions[p.expected_verdicts[0]].append(p)

        if sum(len(submissions[x]) for x in submissions) == 0:
            problem._submissions = False
            return False

        problem._submissions = submissions

        return submissions

    def validators(
        problem, cls: Type[validate.AnyValidator], check_constraints=False, strict=False
    ) -> list[validate.AnyValidator]:
        """
        Gets the validators of the given class.
        If strict is true we only return the validators as the icpc specification indicates.
        If strict is false we may return additional validators (right now we return OutputValidators as AnswerValidators).

        If needed, builds them.

        problem._validators_cache caches previous calls to avoid rebuilding

        Returns:
            singleton list(OutputValidator) if cls is OutputValidator
            list(Validator) otherwise, maybe empty
        """
        if not strict and cls == validate.AnswerValidator:
            return problem._validators(cls, check_constraints) + problem._validators(
                validate.OutputValidator, check_constraints
            )
        else:
            return problem._validators(cls, check_constraints)

    def _validators(
        problem, cls: Type[validate.AnyValidator], check_constraints=False
    ) -> list[validate.AnyValidator]:

        key = (cls, check_constraints)
        if key in problem._validators_cache:
            return problem._validators_cache[key]
        ok = True

        assert hasattr(cls, 'source_dirs')
        paths = [p for source_dir in cls.source_dirs for p in glob(problem.path / source_dir, '*')]

        # Handle default output validation
        if cls == validate.OutputValidator and problem.settings.validation == 'default':
            if paths:
                error("Validation is default but custom output validator exists (ignoring it)")
            paths = [config.tools_root / 'support' / 'default_output_validator.cpp']

        # Check that the proper number of validators is present
        match cls, len(paths):
            case validate.InputValidator, 0:
                warn(f'No input validators found.')
            case validate.AnswerValidator, 0:
                log(f"No answer validators found")
            case validate.OutputValidator, l if l != 1:
                print(cls)
                error(f'Found {len(paths)} output validators, expected exactly one.')
                ok = False

        # TODO: Instead of checking file contents, maybe specify this in generators.yaml?
        def has_constraints_checking(f):
            if not f.is_file():
                return False
            try:
                return 'constraints_file' in f.read_text()
            except UnicodeDecodeError:
                return False

        if check_constraints:
            paths = [
                f
                for f in paths
                if any(
                    has_constraints_checking(source)
                    for source in ([f] if f.is_file() else glob(f, '**/*'))
                )
            ]

        skip_double_build_warning = (
            check_constraints  # or not paths_for_class[Class.ANSWER] TODO not sure about this
        )
        validators = [
            cls(
                problem,
                path,
                skip_double_build_warning=skip_double_build_warning,
                check_constraints=check_constraints,
            )
            for path in paths
        ]
        bar = ProgressBar(f'Building {cls.validator_type} validator', items=validators)
        build_ok = True

        def build_program(p):
            nonlocal build_ok
            localbar = bar.start(p)
            build_ok &= p.build(localbar)
            localbar.done()

        parallel.run_tasks(build_program, validators)

        bar.finalize(print_done=False)

        # All validators must build.
        # TODO Really? Why not at least return those that built?
        result = validators if ok and build_ok else []

        problem._validators_cache[key] = result
        return validators

    def run_submissions(problem):
        testcases = problem.testcases()

        if not testcases:
            return False

        if problem.interactive:
            validators = problem.validators(validate.OutputValidator)
            if not validators:
                return False

        submissions = problem.submissions()
        if not submissions:
            return False

        max_submission_len = max([len(x.name) for cat in submissions for x in submissions[cat]])

        # Pre build the output validator to prevent nested ProgressBars.
        if problem.validators(validate.OutputValidator) is False:
            return False

        ok = True
        verdict_table = verdicts.VerdictTable(submissions, testcases)
        # When true, the ProgressBar will print a newline before the first error log.
        needs_leading_newline = False if config.args.verbose else True
        for verdict in submissions:
            for submission in submissions[verdict]:
                submission_ok, printed_newline = submission.run_all_testcases(
                    max_submission_len,
                    verdict_table=verdict_table,
                    needs_leading_newline=needs_leading_newline,
                )
                needs_leading_newline = not printed_newline
                ok &= submission_ok

        if config.args.table:
            Problem._print_table(verdict_table.results, testcases, submissions)
        elif config.args.overview and not config.args.tree:
            verdict_table.print(force=True, new_lines=1)

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
            assert row[testcase.name] is not None
            if row[testcase.name] is not False:
                return verdicts.to_char(row[testcase.name])
            else:
                return f'{Style.DIM}-{Style.RESET_ALL}'

        make_verdict = lambda tc: ''.join(map(lambda row: single_verdict(row, tc), verdict_table))
        resultant_count, resultant_id = dict[str, int](), dict[str, int]()
        special_id = 0
        for testcase in testcases:
            resultant = make_verdict(testcase)
            if resultant not in resultant_count:
                resultant_count[resultant] = 0
            resultant_count[resultant] += 1
            if resultant_count[resultant] == config.TABLE_THRESHOLD:
                special_id += 1
                resultant_id[resultant] = special_id

        scores = dict[str, float]()
        for t in testcases:
            scores[t.name] = 0
        for dct in verdict_table:
            failures = 0
            for t in testcases:
                if dct[t.name] != verdicts.Verdict.ACCEPTED:
                    failures += 1
            for t in testcases:
                if dct[t.name] != verdicts.Verdict.ACCEPTED:
                    scores[t.name] += 1.0 / failures
        scores_list = sorted(scores.values())

        print(
            '\nVerdict analysis table. Submissions are ordered per column as above. Higher '
            'scores indicate they are critical to break some submissions. Only cases breaking at least one submission are listed.',
            file=sys.stderr,
        )
        fail = (
            verdicts.to_char(verdicts.Verdict.WRONG_ANSWER)
            + verdicts.to_char(verdicts.Verdict.TIME_LIMIT_EXCEEDED)
            + verdicts.to_char(verdicts.Verdict.RUNTIME_ERROR)
        )
        print(f'{fail}: submission fails testcase', file=sys.stderr)
        print(
            f'{verdicts.to_char(verdicts.Verdict.ACCEPTED)}: submission passes testcase\n',
            file=sys.stderr,
        )

        name_col_width = min(50, max([len(testcase.name) for testcase in testcases]))

        for testcase in testcases:
            # Skip all AC testcases
            if all(
                map(
                    lambda row: row[testcase.name] == verdicts.Verdict.ACCEPTED,
                    verdict_table,
                )
            ):
                continue

            name = testcase.name
            if len(name) > name_col_width:
                name = '...' + name[-name_col_width + 3 :]
            padding = ' ' * (name_col_width - len(name))
            print(f'{Fore.CYAN}{name}{Style.RESET_ALL}:{padding}', end=' ', file=sys.stderr)

            color = Style.RESET_ALL
            if len(scores_list) > 6 and scores[testcase.name] >= scores_list[-6]:
                color = Fore.YELLOW
            if len(scores_list) > 3 and scores[testcase.name] >= scores_list[-3]:
                color = Fore.RED
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
        if t.root in ['invalid_input', 'invalid_answer']:
            return None
        h = hash_file_content(t.in_path)
        if h in self._testcase_hashes:
            return self._testcase_hashes[h]
        self._testcase_hashes[h] = t
        return None

    def validate_data(problem, mode: validate.Mode, constraints: dict | bool | None = None) -> bool:
        """Validate aspects of the test data files.

        Arguments:
            mode: validate.Mode.INPUT | validate.Mode.ANSWER | Validate.Mode.INVALID
            constraints: True | dict | None. True means "do check constraints but discard the result."
                False: TODO is this ever used?
        Return:
            True if all validation was successful. Successful validation includes, e.g.,
            correctly rejecting invalid inputs.
        """
        if constraints is True:
            constraints = {}
        assert constraints is None or isinstance(constraints, dict)

        if (problem.interactive or problem.multipass) and mode == validate.Mode.ANSWER:
            if (problem.path / 'answer_validators').exists():
                msg = ''
                if problem.interactive:
                    msg += ' interactive'
                if problem.multipass:
                    msg += ' multi-pass'
                log(f'Not running answer_validators for{msg} problems.')
            return True

        # Pre-build the relevant Validators so as to avoid clash with ProgressBar bar below
        # Also, pick the relevant testcases
        check_constraints = constraints is not None
        match mode:
            case validate.Mode.INPUT:
                problem.validators(validate.InputValidator, check_constraints=check_constraints)
                testcases = problem.testcases(mode=mode)
            case validate.Mode.ANSWER:
                assert not problem.interactive
                assert not problem.multipass
                problem.validators(validate.AnswerValidator, check_constraints=check_constraints)
                testcases = problem.testcases(mode=mode)
            case validate.Mode.INVALID:
                problem.validators(validate.InputValidator)
                if not problem.interactive and not problem.multipass:
                    problem.validators(validate.AnswerValidator)
                testcases = problem.testcases(mode=mode)
            case _:
                raise ValueError(mode)

        # If there are no testcases, validation succeeds
        if not testcases:
            return True

        action = (
            'Invalidation'
            if mode == validate.Mode.INVALID
            else (
                f'{mode} validation' if not check_constraints else f'Collecting {mode} constraints'
            ).capitalize()
        )

        success = True

        problem.reset_testcase_hashes()

        # validate the testcases
        bar = ProgressBar(action, items=[t.name for t in testcases])

        def process_testcase(testcase):
            nonlocal success

            localbar = bar.start(testcase.name)

            if (
                mode == validate.Mode.INPUT
                and not testcase.in_path.is_symlink()
                and not testcase.root == 'invalid_answers'
                and not testcase.root == 'invalid_outputs'
            ):
                t2 = problem.matches_existing_testcase(testcase)
                if t2 is not None:
                    localbar.warn(
                        f'Duplicate testcase: identical to {t2.name}. If this is intentional use symlinks/count/includes.'
                    )
                    localbar.done()
                    return

            ok = testcase.validate_format(mode, bar=localbar, constraints=constraints)
            success &= ok
            localbar.done(ok)

        parallel.run_tasks(process_testcase, testcases)

        bar.finalize(print_done=True)

        # Make sure all constraints are satisfied.
        if constraints:
            for loc, value in sorted(constraints.items()):
                loc = Path(loc).name
                name, has_low, has_high, vmin, vmax, low, high = value
                if not has_low:
                    success = False
                    warn(
                        f'BOUND NOT REACHED: `{name}` never equals lower bound {low}. Min value found: {vmin}'
                    )
                if not has_high:
                    success = False
                    warn(
                        f'BOUND NOT REACHED: `{name}` never equals upper bound {high}. Max value found: {vmax}'
                    )

        return success
