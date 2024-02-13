import hashlib
import random
import io
import re
import shutil
import yaml as yamllib
import collections

from pathlib import Path, PurePosixPath, PurePath

import config
import inspect
import parallel
import program
import run
from testcase import Testcase
import validate

from util import *


def check_type(name, obj, types, path=None):
    if not isinstance(types, list):
        types = [types]
    if any(isinstance(obj, t) for t in types):
        return
    named_types = " or ".join(str(t) if t is None else t.__name__ for t in types)
    if path:
        fatal(
            f'{name} must be of type {named_types}, found {obj.__class__.__name__} at {path}: {obj}'
        )
    else:
        fatal(f'{name} must be of type {named_types}, found {obj.__class__.__name__}: {obj}')


def is_testcase(yaml):
    return (
        yaml == None
        or isinstance(yaml, str)
        or (
            isinstance(yaml, dict)
            and any(
                key in yaml
                for key in ['copy', 'generate', 'in', 'ans', 'out', 'hint', 'desc', 'interaction']
            )
        )
    )


def is_directory(yaml):
    return isinstance(yaml, dict) and not is_testcase(yaml)


# Returns the given path relative to the problem root.
def resolve_path(path, *, allow_absolute, allow_relative):
    assert isinstance(path, str)
    path = PurePosixPath(path)
    if not allow_absolute:
        if path.is_absolute():
            fatal(f'Path must not be absolute: {path}')

    if not allow_relative:
        if not path.is_absolute():
            fatal(f'Path must be absolute: {path}')

    # Make all paths relative to the problem root.
    if path.is_absolute():
        return Path(*path.parts[1:])
    return Path('generators') / path


# testcase_short_path: secret/1.in
def process_testcase(problem, relative_testcase_path):
    if not config.args.testcases:
        return True
    absolute_testcase_path = problem.path / 'data' / relative_testcase_path.with_suffix('')
    for p in config.args.testcases:
        for basedir in get_basedirs(problem, 'data'):
            if is_relative_to(basedir / p, absolute_testcase_path):
                return True
    return False


# An Invocation is a program with command line arguments to execute.
# The following classes inherit from Invocation:
# - GeneratorInvocation
# - SolutionInvocation
# - VisualizerInvocation
class Invocation:
    SEED_REGEX = re.compile(r'\{seed(:[0-9]+)?\}')
    NAME_REGEX = re.compile(r'\{name\}')

    # `string` is the name of the submission (relative to generators/ or absolute from the problem root) with command line arguments.
    # A direct path may also be given.
    def __init__(self, problem, string, *, allow_absolute, allow_relative=True):
        string = str(string)
        commands = string.split()
        command = commands[0]
        self.args = commands[1:]
        self.problem = problem

        # The original command string, used for caching invocation results.
        self.command_string = string

        # The name of the program to be executed, relative to the problem root.
        self.program_path = resolve_path(
            command, allow_absolute=allow_absolute, allow_relative=allow_relative
        )

        # NOTE: This is also used by `fuzz`.
        self.uses_seed = self.SEED_REGEX.search(self.command_string)

        # Make sure that {seed} occurs at most once.
        seed_cnt = 0
        for arg in self.args:
            seed_cnt += len(self.SEED_REGEX.findall(arg))
        if seed_cnt > 1:
            fatal('{seed(:[0-9]+)} may appear at most once.')

        # Automatically set self.program when that program has been built.
        self.program = None

        def callback(program):
            self.program = program

        program.Program.add_callback(problem, problem.path / self.program_path, callback)

    # Return the form of the command used for caching.
    # This is independent of {name} and the actual run_command.
    def cache_command(self, seed=None):
        command_string = self.command_string
        if seed:
            command_string = self.SEED_REGEX.sub(str(seed), command_string)
        return command_string

    def hash(self, seed=None):
        list = []
        if self.program is not None:
            list.append(self.program.hash)
        list.append(self.cache_command(seed))
        return combine_hashes(list)

    # Return the full command to be executed.
    def _sub_args(self, *, seed=None):
        if self.uses_seed:
            assert seed is not None

        def sub(arg):
            arg = self.NAME_REGEX.sub('testcase', arg)
            if self.uses_seed:
                arg = self.SEED_REGEX.sub(str(seed), arg)
            return arg

        return [sub(arg) for arg in self.args]

    # Interface only. Should be implemented by derived class.
    def run(self, bar, cwd, name, seed):
        assert False


class GeneratorInvocation(Invocation):
    def __init__(self, problem, string):
        super().__init__(problem, string, allow_absolute=False)

    # Try running the generator |retries| times, incrementing seed by 1 each time.
    def run(self, bar, cwd, name, seed, retries=1):
        for retry in range(retries):
            result = self.program.run(bar, cwd, name, args=self._sub_args(seed=seed + retry))
            if result.status:
                break
            if not result.retry:
                break

        if not result.status:
            if retries > 1:
                bar.debug(f'{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}')
                bar.error(f'Generator failed {retry + 1} times', result.err)
            else:
                bar.debug(f'{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}')
                bar.error(f'Generator failed', result.err)

        if result.status and config.args.error and result.err:
            bar.log('stderr', result.err)

        return result


class VisualizerInvocation(Invocation):
    def __init__(self, problem, string):
        super().__init__(problem, string, allow_absolute=True, allow_relative=False)

    # Run the visualizer, taking {name} as a command line argument.
    # Stdin and stdout are not used.
    def run(self, bar, cwd, name):
        result = self.program.run(cwd, args=self._sub_args())

        if result.status == ExecStatus.TIMEOUT:
            bar.debug(f'{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}')
            bar.error(f'Visualizer TIMEOUT after {result.duration}s')
        elif not result.status:
            bar.debug(f'{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}')
            bar.error('Visualizer failed', result.err)

        if result.status and config.args.error and result.err:
            bar.log('stderr', result.err)
        return result


class SolutionInvocation(Invocation):
    def __init__(self, problem, string):
        super().__init__(problem, string, allow_absolute=True, allow_relative=False)

    # Run the submission, reading {name}.in from stdin and piping stdout to {name}.ans.
    # If the .ans already exists, nothing is done
    def run(self, bar, cwd, name):
        in_path = cwd / 'testcase.in'
        ans_path = cwd / 'testcase.ans'

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        result = self.program.run(in_path, ans_path, args=self.args, cwd=cwd, default_timeout=True)

        if result.status == ExecStatus.TIMEOUT:
            bar.debug(f'{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}')
            bar.error(f'Solution TIMEOUT after {result.duration}s')
        elif not result.status:
            bar.debug(f'{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}')
            bar.error('Solution failed', result.err)

        if result.status and config.args.error and result.err:
            bar.log('stderr', result.err)
        return result

    def run_interactive(self, problem, bar, cwd, t):
        in_path = cwd / 'testcase.in'
        interaction_path = cwd / 'testcase.interaction'
        if interaction_path.is_file():
            return True

        testcase = Testcase(problem, in_path, short_path=(t.path.parent / (t.name + '.in')))
        r = run.Run(problem, self.program, testcase)

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        ret = r.run(interaction=interaction_path, submission_args=self.args)
        if ret.verdict != 'ACCEPTED':
            bar.error(ret.verdict)
            return False

        return True


# Return absolute path to default submission, starting from the submissions directory.
# This function will always raise a warning.
# Which submission is used is implementation defined, unless one is explicitly given on the command line.
def default_solution_path(generator_config):
    problem = generator_config.problem
    if config.args.default_solution:
        solution = problem.path / config.args.default_solution
        if generator_config.has_yaml:
            log(
                f'''Prefer setting the solution in generators/generators.yaml:
solution: /{solution.relative_to(problem.path)}'''
            )
    else:
        # Use one of the accepted submissions.
        solutions = list(glob(problem.path, 'submissions/accepted/*'))
        if len(solutions) == 0:
            fatal(f'No solution specified and no accepted submissions found.')
            return False
        if generator_config.has_yaml:
            # Note: we explicitly random shuffle the submission that's used to generate answers to
            # encourage setting it in generators.yaml.
            solution = random.choice(solutions)
            solution_short_path = solution.relative_to(problem.path / 'submissions')
            warn(
                f'''No solution specified. Using randomly chosen {solution_short_path} instead.
Set this solution in generators/generators.yaml:
solution: /{solution.relative_to(problem.path)}'''
            )
        else:
            # if the generator.yaml is not used we can be friendly
            solution = min(solutions, key=lambda s: s.name)
            solution_short_path = solution.relative_to(problem.path / 'submissions')
            log(
                f'''No solution specified. Using {solution_short_path} instead. Use
--default_solution {solution.relative_to(problem.path)}
to use a fixed solution.'''
            )

    return Path('/') / solution.relative_to(problem.path)


# A wrapper that lazily initializes the underlying SolutionInvocation on first
# usage.  This is to prevent instantiating the default solution when it's not
# actually needed.
class DefaultSolutionInvocation(SolutionInvocation):
    def __init__(self, generator_config):
        super().__init__(generator_config.problem, default_solution_path(generator_config))

    # Fix the cache_command to prevent regeneration from the random default solution.
    def cache_command(self, seed=None):
        return 'default_solution'


KNOWN_TESTCASE_KEYS = [
    'type',
    'generate',
    'copy',
    'solution',
    'visualizer',
    'random_salt',
    'retries',
] + [e[1:] for e in config.KNOWN_TEXT_DATA_EXTENSIONS]
RESERVED_TESTCASE_KEYS = ['data', 'testdata.yaml', 'include']
KNOWN_DIRECTORY_KEYS = [
    'type',
    'data',
    'testdata.yaml',
    'include',
    'solution',
    'visualizer',
    'random_salt',
    'retries',
]
RESERVED_DIRECTORY_KEYS = ['command']
KNOWN_ROOT_KEYS = ['generators', 'parallel', 'gitignore_generated']


# Holds all inheritable configuration options. Currently:
# - config.solution
# - config.visualizer
# - config.random_salt
class Config:
    # Used at each directory or testcase level.

    def parse_solution(p, x, path):
        check_type('Solution', x, [type(None), str], path)
        if x is None:
            return None
        return SolutionInvocation(p, x)

    def parse_visualizer(p, x, path):
        check_type('Visualizer', x, [type(None), str], path)
        if x is None:
            return None
        return VisualizerInvocation(p, x)

    def parse_random_salt(p, x, path):
        check_type('Random_salt', x, [type(None), str], path)
        if x is None:
            return ''
        return x

    INHERITABLE_KEYS = [
        # True: use an AC submission by default when the solution: key is not present.
        ('solution', True, parse_solution),
        ('visualizer', None, parse_visualizer),
        ('random_salt', '', parse_random_salt),
        # Non-portable keys only used by BAPCtools:
        # The number of retries to run a generator when it fails, each time incrementing the {seed}
        # by 1.
        ('retries', 1, lambda p, x, path: int(x)),
    ]

    def __init__(self, problem, path, yaml=None, parent_config=None):
        assert not yaml or isinstance(yaml, dict)

        for key, default, func in Config.INHERITABLE_KEYS:
            if func is None:
                func = lambda p, x, path: x
            if yaml and key in yaml:
                setattr(self, key, func(problem, yaml[key], path))
            elif parent_config is not None:
                setattr(self, key, getattr(parent_config, key))
            else:
                setattr(self, key, default)


class Rule:
    # key: the dictionary key in the yaml file, i.e. `testcase`
    # name: the numbered testcase name, i.e. `01-testcase`
    def __init__(self, problem, key, name, yaml, parent):
        assert parent is not None

        self.parent = parent

        if isinstance(yaml, dict):
            self.config = Config(problem, parent.path / name, yaml, parent_config=parent.config)
        else:
            self.config = parent.config

        # Yaml key of the current directory/testcase.
        self.key = key
        # Filename of the current directory/testcase.
        self.name = name
        # Path of the current directory/testcase relative to data/.
        self.path: Path = parent.path / self.name


class TestcaseRule(Rule):
    def __init__(self, problem, generator_config, key, name: str, yaml, parent, listed):
        assert is_testcase(yaml)
        assert config.COMPILED_FILE_NAME_REGEX.fullmatch(name + '.in')

        if name.endswith('.in'):
            error(f'Testcase names should not end with \'.in\': {parent.path / name}')
            name = name[:-3]

        # Listed: cases mentioned in generators.yaml.
        self.listed = listed
        # Whether this testcase is a sample.
        self.sample = len(parent.path.parts) > 0 and parent.path.parts[0] == 'sample'

        # 0. Inline: cases where the source is directly in the data/ directory.
        #    This is disjoint from the other options.
        self.inline = False
        # 1. Generator
        self.generator = None
        # 2. Files are copied form this path.
        #    This variable already includes the .in extension, so `.with_suffix()` works nicely.
        self.copy = None
        # 3. Hardcoded cases where the source is in the yaml file itself.
        self.hardcoded = {}

        # Hash of testcase for caching.
        self.hash = None

        # Filled during generate(), since `self.config.solution` will only be set later for the default solution.
        self.cache_data = {}

        # Yaml of rule
        self.rule = {}

        # Used by `fuzz`
        self.in_is_generated = False

        super().__init__(problem, key, name, yaml, parent)

        # root in /data
        self.root = self.path.parts[0]

        # files to consider for hashing
        hashes = {}
        extensions = config.KNOWN_TESTCASE_EXTENSIONS.copy()
        if self.root not in config.INVALID_CASE_DIRECTORIES[1:]:
            extensions.remove('.ans')
        if self.root not in config.INVALID_CASE_DIRECTORIES[2:]:
            extensions.remove('.out')

        if yaml is None:
            self.inline = True
            yaml = dict()
            intarget = self.path.parent / (self.path.name + '.in')
            target_infile = problem.path / 'data' / intarget
            if not target_infile.exists():
                fatal(f'Could not find .in for inline case {intarget}')
            self.hash = hash_file(target_infile)
        else:
            check_type('testcase', yaml, [str, dict])
            if isinstance(yaml, str):
                yaml = {'generate': yaml}
                if yaml['generate'].endswith('.in'):
                    warn(f"Use the new `copy: path/to/case` key instead of {yaml['generate']}.")
                    yaml = {'copy': yaml['generate'][:-3]}

            # checks
            assert (
                'generate' in yaml or 'copy' in yaml or 'in' in yaml or 'interaction' in yaml
            ), f'{parent.path / name}: Testcase requires at least one key in "generate", "copy", "in", "interaction".'
            assert not (
                'submission' in yaml and 'ans' in yaml
            ), f'{parent.path / name}: cannot specify both "submissions" and "ans".'

            # 1. generate
            if 'generate' in yaml:
                check_type('generate', yaml['generate'], str)
                if len(yaml['generate']) == 0:
                    fatal(f'`generate` must not be empty')

                self.generator = GeneratorInvocation(problem, yaml['generate'])

                # TODO: Should the seed depend on white space? For now it does, but
                # leading and trailing whitespace is stripped.
                seed_value = self.config.random_salt + yaml['generate'].strip()
                self.seed = int(hashlib.sha512(seed_value.encode('utf-8')).hexdigest(), 16) % (
                    2**31
                )
                self.in_is_generated = True
                self.rule['gen'] = self.generator.command_string
                if self.generator.uses_seed:
                    self.rule['seed'] = self.seed
                hashes['.in'] = self.generator.hash(self.seed)

            # 2. path
            if 'copy' in yaml:
                check_type('`copy`', yaml['copy'], str)
                if Path(yaml['copy']).suffix in config.KNOWN_TEXT_DATA_EXTENSIONS:
                    warn(f"`copy: {yaml['copy']}` should not include the extension.")
                self.copy = resolve_path(yaml['copy'], allow_absolute=False, allow_relative=True)
                self.copy = problem.path / self.copy.parent / (self.copy.name + '.in')
                if self.copy.is_file():
                    self.in_is_generated = False
                self.rule['copy'] = str(self.copy)
                for ext in extensions:
                    if self.copy.with_suffix(ext).is_file():
                        hashes[ext] = hash_file(self.copy.with_suffix(ext))

            # 3. hardcoded
            for ext in config.KNOWN_TEXT_DATA_EXTENSIONS:
                if ext[1:] in yaml:
                    value = yaml[ext[1:]]
                    check_type(ext, value, str)
                    if len(value) > 0 and value[-1] != '\n':
                        value += '\n'
                    self.hardcoded[ext] = value

            if '.in' in self.hardcoded:
                self.in_is_generated = False
                self.rule['in'] = self.hardcoded['.in']
            for ext in extensions:
                if ext in self.hardcoded:
                    hashes[ext] = hash_string(self.hardcoded[ext])

        # Warn/Error for unknown keys.
        for key in yaml:
            if key in RESERVED_TESTCASE_KEYS:
                fatal('Testcase must not contain reserved key {key}.')
            if key not in KNOWN_TESTCASE_KEYS:
                if config.args.action == 'generate':
                    log(f'Unknown testcase level key: {key} in {self.path}')

        if not '.in' in hashes:
            # An error is shown during generate.
            return

        # build ordered list of hashes we want to consider
        self.hash = [hashes[ext] for ext in config.KNOWN_TESTCASE_EXTENSIONS if ext in hashes]

        # combine hashes
        if len(self.hash) == 1:
            self.hash = self.hash[0]
        else:
            self.hash = combine_hashes(self.hash)

        # Error for listed cases with identical input.
        if self.listed and self.hash in generator_config.rules_cache:
            # This is fatal to prevent crashes later on when running generators in parallel.
            # https://github.com/RagnarGrootKoerkamp/BAPCtools/issues/310
            fatal(
                f'Found identical input at {generator_config.rules_cache[self.hash]} and {self.path}'
            )
        generator_config.rules_cache[self.hash] = self.path

    def generate(t, problem, generator_config, parent_bar):
        bar = parent_bar.start(str(t.path))

        t.generate_success = False

        # Some early checks.
        if t.generator and t.generator.program is None:
            bar.done(False, f'Generator didn\'t build.')
            return

        target_dir = problem.path / 'data' / t.path.parent
        target_infile = target_dir / (t.name + '.in')
        target_ansfile = target_dir / (t.name + '.ans')

        # Clean up duplicate unlisted testcases, or warn if distinct.
        if not t.listed and generator_config.has_yaml:
            if t.hash in generator_config.generated_testdata:
                for ext in config.KNOWN_DATA_EXTENSIONS:
                    ext_file = target_infile.with_suffix(ext)
                    if ext_file.is_file():
                        ext_file.unlink()
                bar.debug(
                    f'DELETED unlisted duplicate of {generator_config.generated_testdata[t.hash].path}'
                )
            else:
                bar.error(f'Testcase not listed in generator.yaml (delete using --clean).')
            bar.done()
            return

        # Input can only be missing when the `copy:` does not have a corresponding `.in` file.
        # (When `generate:` or `in:` is used, the input is always present.)
        if t.hash is None:
            bar.done(False, f'{t.copy} does not exist.')
            return

        # E.g. bapctmp/problem/data/<hash>.in
        cwd = problem.tmpdir / 'data' / t.hash
        cwd.mkdir(parents=True, exist_ok=True)
        infile = cwd / 'testcase.in'
        ansfile = cwd / 'testcase.ans'
        meta_path = cwd / 'meta_.yaml'

        def init_meta():
            meta_yaml = read_yaml(meta_path) if meta_path.is_file() else None
            if meta_yaml is None:
                meta_yaml = {'validator_hashes': dict()}
            meta_yaml['rule'] = t.rule
            return meta_yaml

        meta_yaml = init_meta()
        write_yaml(meta_yaml, meta_path.open('w'), allow_yamllib=True)

        # Check whether the generated data and validation are up to date.
        # Returns (generator/input up to date, validation up to date)
        def up_to_date():
            # The testcase is up to date if:
            # - both target infile ans ansfile exist
            # - meta_ contains exactly the right content (commands and hashes)
            # - each validator with correct flags has been run already.
            if t.copy:
                t.cache_data['source_hash'] = t.hash
            for ext, string in t.hardcoded.items():
                t.cache_data['hardcoded_' + ext[1:]] = hash_string(string)
            if t.generator:
                t.cache_data['generator_hash'] = t.generator.hash(seed=t.seed)
                t.cache_data['generator'] = t.generator.cache_command(seed=t.seed)
            if t.config.solution:
                t.cache_data['solution_hash'] = t.config.solution.hash()
                t.cache_data['solution'] = t.config.solution.cache_command()
            if t.config.visualizer:
                t.cache_data['visualizer_hash'] = t.config.visualizer.hash()
                t.cache_data['visualizer'] = t.config.visualizer.cache_command()

            if config.args.all:
                return (False, False)

            if not infile.is_file():
                return (False, False)
            if not ansfile.is_file():
                return (False, False)
            if (
                problem.interactive
                and t.sample
                and not ansfile.with_suffix('.interaction').is_file()
            ):
                return (False, False)

            if not meta_path.is_file():
                return (False, False)

            meta_yaml = read_yaml(meta_path)
            # In case meta_yaml is malformed, things are not up to date.
            if not isinstance(meta_yaml, dict):
                return (False, False)
            if meta_yaml.get('cache_data') != t.cache_data:
                return (False, False)

            # Check whether all input validators have been run.
            testcase = Testcase(problem, infile, short_path=t.path / t.name)
            for h in testcase.validator_hashes(validate.InputValidator):
                if h not in meta_yaml.get('validator_hashes', []):
                    return (True, False)
            return (True, True)

        # For each generated .in file check that they
        # use a deterministic generator by rerunning the generator with the
        # same arguments.  This is done when --check-deterministic is passed,
        # which is also set to True when running `bt all`.
        # This doesn't do anything for non-generated cases.
        # It also checks that the input changes when the seed changes.
        def check_deterministic(force=False):
            if not force and not config.args.check_deterministic:
                return False

            if t.generator is None:
                return True

            # Check that the generator is deterministic.
            # TODO: Can we find a way to easily compare cpython vs pypy? These
            # use different but fixed implementations to hash tuples of ints.
            tmp = cwd / 'tmp'
            tmp.mkdir(parents=True, exist_ok=True)
            tmp_infile = tmp / 'testcase.in'
            result = t.generator.run(bar, tmp, tmp_infile.stem, t.seed, t.config.retries)
            if not result.status:
                return

            # This is checked when running the generator.
            assert infile.is_file()

            # Now check that the source and target are equal.
            if infile.read_bytes() == tmp_infile.read_bytes():
                if config.args.check_deterministic:
                    bar.part_done(True, 'Generator is deterministic.')
            else:
                bar.part_done(
                    False, f'Generator `{t.generator.command_string}` is not deterministic.'
                )

            # If {seed} is used, check that the generator depends on it.
            if t.generator.uses_seed:
                depends_on_seed = False
                for run in range(config.SEED_DEPENDENCY_RETRIES):
                    new_seed = (t.seed + 1 + run) % (2**31)
                    result = t.generator.run(bar, tmp, tmp_infile.stem, new_seed, t.config.retries)
                    if not result.status:
                        return

                    # Now check that the source and target are different.
                    if infile.read_bytes() != tmp_infile.read_bytes():
                        depends_on_seed = True
                        break

                if depends_on_seed:
                    if config.args.check_deterministic:
                        bar.debug('Generator depends on seed.')
                else:
                    bar.log(
                        f'Generator `{t.generator.command_string}` likely does not depend on seed:',
                        f'All values in [{t.seed}, {new_seed}] give the same result.',
                    )

        # Returns False when some files were skipped.
        def move_generated():
            if t.path.parents[0] == Path('sample'):
                msg = '; supply -f --samples to overwrite'
                # This should display as a log instead of warning.
                warn = False
                forced = config.args.force and (config.args.action == 'all' or config.args.samples)
            else:
                msg = '; supply -f to overwrite'
                warn = True
                forced = config.args.force

            all_done = True

            # For inline cases, only copy the (possibly) generated .ans.
            # Any other files in the directory are kept without warning.
            extentions = ['.ans'] if t.inline else config.KNOWN_DATA_EXTENSIONS
            for ext in extentions:
                source = infile.with_suffix(ext)
                target = target_infile.with_suffix(ext)

                if source.is_file():
                    if target.is_file():
                        if source.read_bytes() == target.read_bytes():
                            # identical -> skip
                            continue
                        else:
                            # different -> overwrite
                            if not forced:
                                if warn:
                                    bar.warn(f'SKIPPED: {target.name}{Style.RESET_ALL}' + msg)
                                else:
                                    bar.log(f'SKIPPED: {target.name}{Style.RESET_ALL}' + msg)
                                skipped = True
                                if ext == '.in':
                                    skipped_in = True
                                continue
                            bar.log(f'CHANGED {target.name}')
                    else:
                        # new file -> move it
                        bar.log(f'NEW {target.name}')

                    if target.is_symlink():
                        # Make sure that we write to target, and not to the file pointed to by target.
                        target.unlink()

                    # We always copy file contents. Unlisted cases are copied as well.
                    shutil.copy(source, target, follow_symlinks=True)
                else:
                    if target.is_file():
                        # Target exists but source wasn't generated. Only remove the target with -f.
                        # When solution is disabled, this is fine for the .ans file.
                        if ext == '.ans' and t.config.solution is None:
                            continue

                        # remove old target
                        if not forced:
                            if warn:
                                bar.warn(f'SKIPPED: {target.name}{Style.RESET_ALL}' + msg)
                            else:
                                bar.log(f'SKIPPED: {target.name}{Style.RESET_ALL}' + msg)
                            skipped = True
                            continue
                        else:
                            bar.log(f'REMOVED {target.name}')
                            target.unlink()
                    else:
                        # both source and target do not exist
                        continue
            return all_done

        def add_testdata_to_cache():
            # Store the generated testdata for deduplication test cases.
            hashes = {}

            # remove files that should not be considered for this testcase
            extensions = config.KNOWN_TESTCASE_EXTENSIONS.copy()
            if t.root not in config.INVALID_CASE_DIRECTORIES[1:]:
                extensions.remove('.ans')
            if t.root not in config.INVALID_CASE_DIRECTORIES[2:]:
                extensions.remove('.out')

            for ext in extensions:
                if target_infile.with_suffix(ext).is_file():
                    hashes[ext] = hash_file(target_infile.with_suffix(ext))

            # build ordered list of hashes we want to consider
            test_hash = [hashes[ext] for ext in extensions if ext in hashes]

            # combine hashes
            if len(test_hash) == 1:
                test_hash = test_hash[0]
            else:
                test_hash = combine_hashes(test_hash)

            # check for duplicates
            if test_hash not in generator_config.generated_testdata:
                generator_config.generated_testdata[test_hash] = t
            else:
                bar.warn(
                    f'Testcase {t.path} is equal to {generator_config.generated_testdata[test_hash].path}.'
                )

        generator_up_to_date, validator_up_to_date = up_to_date()
        if not validator_up_to_date:
            if not generator_up_to_date:
                # clear all generated files
                shutil.rmtree(cwd)
                cwd.mkdir(parents=True, exist_ok=True)
                meta_yaml = init_meta()
                write_yaml(meta_yaml, meta_path.open('w'), allow_yamllib=True)

                # Step 1: run `generate:` if present.
                if t.generator:
                    result = t.generator.run(bar, cwd, infile.stem, t.seed, t.config.retries)
                    if not result.status:
                        return

                # Step 2: Copy `copy:` files for all known extensions.
                if t.copy:
                    # We make sure to not silently overwrite changes to files in data/
                    # that are copied from generators/.
                    copied = False
                    for ext in config.KNOWN_DATA_EXTENSIONS:
                        ext_file = t.copy.with_suffix(ext)
                        if ext_file.is_file():
                            shutil.copy(ext_file, infile.with_suffix(ext), follow_symlinks=True)
                            copied = True
                    if not copied:
                        bar.warn(f'No files copied from {t.copy}.')

                # Step 3: Write hardcoded files.
                for ext, contents in t.hardcoded.items():
                    if contents == '' and not t.root in ['bad', 'invalid_inputs']:
                        bar.error(f'Hardcoded {ext} data must not be empty!')
                        return
                    else:
                        infile.with_suffix(ext).write_text(contents)

                # Step 4: If inline copy the source file.
                if t.inline:
                    if not target_infile.is_file():
                        # Step 5a: Error if target_infile for inline case does not exist.
                        bar.error(f'No .in file was found for inline testcase')
                        return
                    shutil.copy(target_infile, infile, follow_symlinks=True)
                else:
                    if not infile.is_file():
                        # Step 5b: Error if infile was not generated.
                        bar.error(f'No .in file was generated!')
                        return

            assert infile.is_file(), f'Expected .in file not found in cache: {infile}'
            testcase = Testcase(problem, infile, short_path=t.path / t.name)

            # Validate the in.
            no_validators = config.args.no_validators

            if not testcase.validate_format(
                validate.Mode.INPUT, bar=bar, constraints=None, warn_instead_of_error=no_validators
            ):
                if not no_validators:
                    if t.generator:
                        bar.warn(
                            'Failed generator command: '
                            + (
                                ' '.join(
                                    [
                                        str(t.generator.program_path),
                                        *t.generator._sub_args(seed=t.seed),
                                    ]
                                )
                                if t.generator.uses_seed
                                else t.generator.command_string
                            ),
                        )
                    bar.debug('Use generate --no-validators to ignore validation results.')
                    return

            if not generator_up_to_date:
                # Generate .ans and .interaction if needed.
                if (
                    not config.args.no_solution
                    and testcase.root not in config.INVALID_CASE_DIRECTORIES
                ):
                    if not problem.interactive:
                        # Generate a .ans if not already generated by earlier steps.
                        if not testcase.ans_path.is_file():
                            # Run the solution if available.
                            if t.config.solution:
                                if not t.config.solution.run(bar, cwd, infile.stem).status:
                                    return
                            elif t.inline:
                                # Otherwise, copy the .ans for inline cases.
                                if not target_ansfile.is_file():
                                    # Error if target_ansfile and `solution` for inline cases both do not exist.
                                    bar.error(
                                        f'No solution or .ans file was found for inline testcase'
                                    )
                                    bar.done()
                                    return
                                shutil.copy(target_ansfile, ansfile, follow_symlinks=True)
                            else:
                                # Otherwise, it's a hard error.
                                bar.error(f'{ansfile.name} does not exist and was not generated.')
                                bar.done()
                                return

                        # Validate the ans file.
                        assert ansfile.is_file(), f'Failed to generate ans file: {ansfile}'
                        if not testcase.validate_format(
                            validate.Mode.ANSWER, bar=bar, warn_instead_of_error=no_validators
                        ):
                            if not no_validators:
                                bar.debug(
                                    'Use generate --no-validators to ignore validation results.'
                                )
                                return
                    else:
                        if not testcase.ans_path.is_file():
                            testcase.ans_path.write_text('')
                        # For interactive problems, run the interactive solution and generate a .interaction.
                        if (
                            t.config.solution
                            and (testcase.root == 'sample' or config.args.interaction)
                            and '.interaction' not in t.hardcoded
                        ):
                            if not t.config.solution.run_interactive(problem, bar, cwd, t):
                                return

                # Generate visualization
                if not config.args.no_visualizer and t.config.visualizer:
                    # Note that the .in/.ans are generated even when the visualizer fails.
                    t.config.visualizer.run(bar, cwd, infile.stem)

                check_deterministic(True)

            meta_yaml['cache_data'] = t.cache_data
            if generator_up_to_date:
                hashes = testcase.validator_hashes(validate.InputValidator)
                for h in hashes:
                    meta_yaml['validator_hashes'][h] = hashes[h]
            else:
                meta_yaml['validator_hashes'] = testcase.validator_hashes(validate.InputValidator)

            # Update metadata
            if move_generated():
                write_yaml(meta_yaml, meta_path.open('w'), allow_yamllib=True)
            message = ''
        else:
            if config.args.action != 'generate':
                bar.logged = True  # Disable redundant 'up to date' message in run mode.
            check_deterministic(False)
            message = 'up to date'
            move_generated()

        # Note that we set this to true even if not all files were overwritten -- a different log/warning message will be displayed for that.
        t.generate_success = True
        add_testdata_to_cache()
        bar.done(message=message)


# Helper that has the required keys needed from a parent directory.
class RootDirectory:
    path = Path('')
    config = None
    numbered = False


class Directory(Rule):
    # Process yaml object for a directory.
    def __init__(self, problem, key, name: str, yaml: dict = None, parent=None, listed=True):
        assert is_directory(yaml)
        # The root Directory object has name ''.
        if name != '':
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(name):
                fatal(f'Directory "{name}" does not have a valid name.')

        super().__init__(problem, key, name, yaml, parent)

        if name == '':
            for key in yaml:
                if key in RESERVED_DIRECTORY_KEYS:
                    fatal(f'Directory must not contain reserved key {key}.')
                if key not in KNOWN_DIRECTORY_KEYS + KNOWN_ROOT_KEYS:
                    if config.args.action == 'generate':
                        log(f'Unknown root level key: {key}')
        else:
            for key in yaml:
                if key in RESERVED_DIRECTORY_KEYS + KNOWN_ROOT_KEYS:
                    fatal(f'Directory must not contain reserved key {key}.')
                if key not in KNOWN_DIRECTORY_KEYS:
                    if config.args.action == 'generate':
                        log(f'Unknown directory level key: {key} in {self.path}')

        if 'testdata.yaml' in yaml:
            self.testdata_yaml = yaml['testdata.yaml']
        else:
            self.testdata_yaml = False

        self.listed = listed
        self.numbered = False

        # List of child TestcaseRule/Directory objects, filled by parse().
        self.data = []
        # Map of short_name => TestcaseRule, filled by parse().
        self.includes = dict()
        # List of unlisted included symlinks, filled by parse().
        self.unlisted_includes = []

        # Sanity checks for possibly empty data.
        if 'data' not in yaml:
            return
        data = yaml['data']
        if data is None:
            return
        if data == '':
            return
        check_type('Data', data, [dict, list])

        if isinstance(data, dict):
            yaml['data'] = [data]
            data = yaml['data']
        else:
            self.numbered = True
            if len(data) == 0:
                return

            for d in data:
                check_type('Numbered case', d, dict)
                if len(d) != 1:
                    if 'in' in d or 'ans' in d or 'copy' in d:
                        fatal(
                            f'{self.path}: Dictionary must contain exactly one named testcase/group.\nTo specify hardcoded in/ans/copy, indent one more level.'
                        )
                    else:
                        fatal(
                            f'{self.path}: Dictionary must contain exactly one named testcase/group.'
                        )

    # Map a function over all test cases directory tree.
    # dir_f by default reuses testcase_f
    def walk(self, testcase_f=None, dir_f=True, *, dir_last=False):
        if dir_f is True:
            dir_f = testcase_f

        if not dir_last and dir_f:
            dir_f(self)

        for d in self.data:
            if isinstance(d, Directory):
                d.walk(testcase_f, dir_f, dir_last=dir_last)
            elif isinstance(d, TestcaseRule):
                if testcase_f:
                    testcase_f(d)
            else:
                assert False

        if dir_last and dir_f:
            dir_f(self)

    def generate(d, problem, generator_config, bar):
        # Generate the current directory:
        # - Create the directory.
        # - Write testdata.yaml.
        # - Link included testcases.
        #   - Input of included testcases are re-validated with the
        #     directory-specific input validator flags.
        bar.start(str(d.path))

        # Create the directory.
        dir_path = problem.path / 'data' / d.path
        dir_path.mkdir(parents=True, exist_ok=True)

        # Write the testdata.yaml, or remove it when the key is set but empty.
        testdata_yaml_path = dir_path / 'testdata.yaml'
        if d.testdata_yaml is False:
            if testdata_yaml_path.is_file():
                bar.error(f'Unlisted testdata.yaml (delete using --clean)')
        else:
            if d.testdata_yaml:
                yaml_text = yamllib.dump(dict(d.testdata_yaml))
                if not testdata_yaml_path.is_file():
                    testdata_yaml_path.write_text(yaml_text)
                else:
                    if yaml_text != testdata_yaml_path.read_text():
                        if config.args.force:
                            bar.log(f'CHANGED testdata.yaml')
                            testdata_yaml_path.write_text(yaml_text)
                        else:
                            bar.warn(f'SKIPPED: testdata.yaml')

            if d.testdata_yaml == '' and testdata_yaml_path.is_file():
                bar.log(f'DELETED: testdata.yaml')
                testdata_yaml_path.unlink()
        bar.done()

        for key in d.includes:
            t = d.includes[key]
            target = t.path
            new_case = d.path / target.name
            bar.start(str(new_case))
            infile = problem.path / 'data' / target.parent / (target.name + '.in')

            if not t.generate_success:
                bar.error(f'Included case {target} has errors.')
                bar.done()
                continue

            if not infile.is_file():
                bar.warn(f'{target}.in does not exist.')
                bar.done()
                continue

            # Check if the testcase was already validated.
            # TODO: Dedup some of this with TestcaseRule.generate?
            cwd = problem.tmpdir / 'data' / t.hash
            meta_path = cwd / 'meta_.yaml'
            assert (
                meta_path.is_file()
            ), f"Metadata file not found for included case {d.path / key}\nwith hash {t.hash}\nfile {meta_path}"
            meta_yaml = read_yaml(meta_path)
            testcase = Testcase(problem, infile, short_path=t.path / t.name)
            hashes = testcase.validator_hashes(validate.InputValidator)

            # All hashes validated before?
            def up_to_date():
                for h in hashes:
                    if h not in meta_yaml.get('validator_hashes', []):
                        return False
                return True

            if not up_to_date():
                # Validate the testcase input.
                testcase = Testcase(problem, infile, short_path=new_case)
                if not testcase.validate_format(
                    validate.Mode.INPUT,
                    bar=bar,
                    constraints=None,
                    warn_instead_of_error=config.args.no_validators,
                ):
                    if not config.args.no_validators:
                        bar.debug('Use generate --no-validators to ignore validation results.')
                        bar.done()
                        continue
                # Add hashes to the cache.
                for h in hashes:
                    if 'validator_hashes' not in meta_yaml:
                        meta_yaml['validator_hashes'] = dict()
                    meta_yaml['validator_hashes'][h] = hashes[h]

                # Update metadata
                yamllib.dump(
                    meta_yaml,
                    meta_path.open('w'),
                )

            # TODO: Validate the testcase output as well?

            for ext in config.KNOWN_DATA_EXTENSIONS:
                t = infile.with_suffix(ext)
                if t.is_file():
                    # TODO: In case a distinct file/symlink already exists, warn
                    # and require -f, like for usual testcases.
                    ensure_symlink(dir_path / t.name, t, relative=True)
                    # This is debug, since it's too verbose to always show, and
                    # only showing on changes is kinda annoying.
                    # TODO: Maybe we can update `ensure_symlink` to return
                    # whether anything (an existing symlink/copy) was changed.
                    bar.debug(f'INCLUDED {t.name}')
            bar.done()

    # Clean up or warn for unlisted includes.
    # Separate function that's run after the generation of listed dirs/cases.
    def generate_unlisted(d, problem, generator_config, bar):
        for name in d.unlisted_includes:
            f = problem.path / 'data' / d.path / (name + '.in')
            assert f.is_symlink()
            target = f.readlink()
            bar.start(str(d.path / name))
            # Broken symlink
            if not f.exists():
                if config.args.force:
                    for ext in config.KNOWN_DATA_EXTENSIONS:
                        ext_file = f.with_suffix(ext)
                        if ext_file.is_symlink():
                            ext_file.unlink()
                    bar.log(f'Deleted broken include to {target}.')
                else:
                    bar.error(f'Include with target {target} does not exist.')
            else:
                bar.log(f'Include target {target} exists')
            bar.done()

        return True


# Returns a pair (numbered_name, basename)
def numbered_testcase_name(basename, i, n):
    width = len(str(n))
    number_prefix = f'{i:0{width}}'
    if basename:
        return number_prefix + '-' + basename
    else:
        assert basename is None or basename == ''
        return number_prefix


class GeneratorConfig:
    def parse_generators(generators_yaml):
        check_type('Generators', generators_yaml, dict)
        generators = {}
        for gen in generators_yaml:
            assert not gen.startswith('/')
            assert not Path(gen).is_absolute()
            assert config.COMPILED_FILE_NAME_REGEX.fullmatch(gen + '.x')

            deps = generators_yaml[gen]
            check_type('Generator dependencies', deps, list)
            if len(deps) == 0:
                fatal('Generator dependencies must not be empty.')
            for d in deps:
                check_type('Generator dependencies', d, str)

            generators[Path('generators') / gen] = [Path('generators') / d for d in deps]
        return generators

    # Only used at the root directory level.
    ROOT_KEYS = [
        ('generators', {}, parse_generators),
        # Non-standard key. When set to True, all generated testcases will be .gitignored from data/.gitignore.
        ('gitignore_generated', False, lambda x: x is True),
    ]

    # Parse generators.yaml.
    def __init__(self, problem):
        self.problem = problem
        yaml_path = self.problem.path / 'generators/generators.yaml'
        self.ok = True

        # A map of paths `secret/testgroup/testcase` to their canonical TestcaseRule.
        # For generated cases this is the rule itself.
        # For included cases, this is the 'resolved' location of the testcase that is included.
        self.known_cases = dict()
        # A set of paths `secret/testgroup`.
        # Used for cleanup.
        self.known_directories = set()
        # A map from key to (is_included, list of testcases and directories),
        # used for `include` statements.
        self.known_keys = collections.defaultdict(lambda: [False, []])
        # A set of testcase rules, including seeds.
        self.rules_cache = dict()
        # The set of generated testcases keyed by hash(testdata).
        self.generated_testdata = dict()

        if yaml_path.is_file():
            yaml = read_yaml(yaml_path)
            self.has_yaml = True
        else:
            yaml = None
            self.has_yaml = False
            if config.args.action == 'generate':
                log('Did not find generators/generators.yaml')

        self.parse_yaml(yaml)

    def parse_yaml(self, yaml):
        check_type('Root yaml', yaml, [type(None), dict])
        if yaml is None:
            yaml = dict()

        # Read root level configuration
        for key, default, func in GeneratorConfig.ROOT_KEYS:
            if yaml and key in yaml:
                setattr(self, key, func(yaml[key] if yaml[key] is not None else default))
            else:
                setattr(self, key, default)

        def add_known(obj, listed):
            path = obj.path
            name = path.name
            if isinstance(obj, TestcaseRule):
                self.known_cases[path] = obj
            elif isinstance(obj, Directory):
                self.known_directories.add(path)
            else:
                assert False

            if listed:
                key = self.known_keys[obj.key]
                key[1].append(obj)
                if key[0] and len(key[1]) == 2:
                    error(
                        f'{obj.path}: Included key {name} exists more than once as {key[1][0].path} and {key[1][1].path}.'
                    )

        num_numbered_testcases = 0
        testcase_id = 0

        # Count the number of testcases in the given directory yaml.
        # This parser is quite forgiving,
        def count(yaml):
            nonlocal num_numbered_testcases
            ds = yaml.get('data')
            if isinstance(ds, dict):
                ds = [ds]
                numbered = False
            else:
                numbered = True
            if not isinstance(ds, list):
                return
            for elem in ds:
                if isinstance(elem, dict):
                    for key in elem:
                        if is_testcase(elem[key]) and numbered:
                            # TODO (#271): Count the number of generated cases for `count:` and/or variables.
                            num_numbered_testcases += 1
                        elif is_directory(elem[key]):
                            count(elem[key])

        count(yaml)

        # Main recursive parsing function.
        # key: the yaml key e.g. 'testcase'
        # name: the possibly numbered name e.g. '01-testcase'
        def parse(key, name, yaml, parent, listed=True):
            nonlocal testcase_id
            # Skip unlisted `data/bad` directory: we should not generate .ans files there.
            if (
                name in config.INVALID_CASE_DIRECTORIES
                and parent.path == Path('.')
                and listed is False
            ):
                return None

            check_type('Testcase/directory', yaml, [type(None), str, dict], parent.path)
            if not is_testcase(yaml) and not is_directory(yaml):
                fatal(f'Could not parse {parent.path / name} as a testcase or directory.')

            if is_testcase(yaml):
                if not config.COMPILED_FILE_NAME_REGEX.fullmatch(name + '.in'):
                    error(f'Testcase \'{parent.path}/{name}.in\' has an invalid name.')
                    return None

                # If a list of testcases was passed and this one is not in it, skip it.
                if not process_testcase(self.problem, parent.path / name):
                    return None

                t = TestcaseRule(self.problem, self, key, name, yaml, parent, listed=listed)
                assert t.path not in self.known_cases, f"{t.path} was already parsed"
                add_known(t, listed)
                return t

            assert is_directory(yaml)

            d = Directory(self.problem, key, name, yaml, parent, listed=listed)
            assert d.path not in self.known_cases
            assert d.path not in self.known_directories
            add_known(d, listed)

            # Parse child directories/testcases.
            # First loop over explicitly mentioned testcases/directories, and then find remaining on-disk files/dirs.
            if 'data' in yaml and yaml['data']:
                # Count the number of child testgroups.
                num_testgroups = 0
                for dictionary in d.data:
                    check_type('Elements of data', dictionary, dict, d.path)
                    for child_name, child_yaml in sorted(dictionary.items()):
                        if is_directory(child_yaml):
                            num_testgroups += 1

                testgroup_id = 0
                for dictionary in yaml['data']:
                    for key in dictionary:
                        check_type('Testcase/directory name', key, [type(None), str], d.path)

                    for child_key, child_yaml in sorted(dictionary.items()):
                        if d.numbered:
                            if is_directory(child_yaml):
                                testgroup_id += 1
                                child_name = numbered_testcase_name(
                                    child_key, testgroup_id, num_testgroups
                                )
                            elif is_testcase(child_yaml):
                                # TODO: For now, testcases are numbered per testgroup. This will change soon.
                                testcase_id += 1
                                child_name = numbered_testcase_name(
                                    child_key, testcase_id, num_numbered_testcases
                                )
                            else:
                                # Use error will be given inside parse(child).
                                child_name = ''

                        else:
                            child_name = child_key
                            if not child_name:
                                fatal(
                                    f'Unnumbered testcases must not have an empty key: {Path("data") / d.path / child_name}/\'\''
                                )
                        c = parse(child_key, child_name, child_yaml, d, listed=listed)
                        if c is not None:
                            d.data.append(c)

            # Include TestcaseRule t for the current directory.
            def add_included_case(t):
                # Unlisted cases are never included.
                if not t.listed:
                    return

                target = t.path
                name = target.name
                p = d.path / name
                if p in self.known_cases:
                    if target != self.known_cases[p].path:
                        if self.known_cases[p].path == p:
                            error(f'{d.path/name} conflicts with included case {target}.')
                        else:
                            error(
                                f'{d.path/name} is included with multiple targets {target} and {self.known_cases[p].path}.'
                            )
                    return
                self.known_cases[p] = t
                d.includes[name] = t

            if 'include' in yaml:
                check_type('includes', yaml['include'], list, d.path)

                for include in yaml['include']:
                    check_type('include', include, str, d.path)
                    if '/' in include:
                        error(
                            f"{d.path}: Include {include} should be a testcase/testgroup key, not a path."
                        )
                        continue

                    if include in self.known_keys:
                        key = self.known_keys[include]
                        if len(key[1]) != 1:
                            error(f'{d.path}: Included key {include} exists more than once.')
                            continue

                        key[0] = True
                        obj = key[1][0]
                        if isinstance(obj, TestcaseRule):
                            add_included_case(obj)
                        else:
                            # NOTE: Only listed cases are included
                            obj.walk(
                                add_included_case,
                                lambda d: [add_included_case(t) for t in d.includes.values()],
                            )
                            pass
                    else:
                        error(
                            f'{d.path}: Unknown include key {include} does not refer to a lexicographically smaller testcase.'
                        )
                        continue

            # Find unlisted testcases and directories.
            dir_path = self.problem.path / 'data' / d.path
            if dir_path.is_dir():
                for f in sorted(dir_path.iterdir()):
                    # f must either be a directory or a .in file.
                    if not (f.is_dir() or f.suffix == '.in'):
                        continue

                    # Testcases are always passed as name without suffix.
                    f_in = f
                    if not f.is_dir():
                        f = f.with_suffix('')

                    # Skip already processed cases.
                    if (d.path / f.name in self.known_cases) or (
                        d.path / f.name in self.known_directories
                    ):
                        continue

                    # Broken or valid symlink.
                    if f_in.is_symlink():
                        d.unlisted_includes.append(f.name)
                        continue

                    # Generate stub yaml so we can call `parse` recursively.
                    child_yaml = None
                    if f.is_dir():
                        child_yaml = {}

                    c = parse(f.name, f.name, child_yaml, d, listed=False)
                    if c is not None:
                        d.data.append(c)

            return d

        self.root_dir = parse('', '', yaml, RootDirectory())

    def build(self, build_visualizers=True):
        if config.args.add_unlisted or config.args.clean or config.args.clean_generated:
            return

        generators_used = set()
        solutions_used = set()
        visualizers_used = set()

        # Collect all programs that need building.
        # Also, convert the default submission into an actual Invocation.
        default_solution = None

        def collect_programs(t):
            if isinstance(t, TestcaseRule):
                if t.generator:
                    generators_used.add(t.generator.program_path)
            if t.config.solution:
                if config.args.no_solution:
                    t.config.solution = None
                else:
                    # Initialize the default solution if needed.
                    if t.config.solution is True:
                        nonlocal default_solution
                        if default_solution is None:
                            default_solution = DefaultSolutionInvocation(self)
                        t.config.solution = default_solution
                    solutions_used.add(t.config.solution.program_path)
            if build_visualizers and t.config.visualizer:
                visualizers_used.add(t.config.visualizer.program_path)

        self.root_dir.walk(collect_programs, dir_f=None)

        def build_programs(program_type, program_paths):
            programs = []
            for program_path in program_paths:
                path = self.problem.path / program_path
                deps = None
                if program_type is program.Generator and program_path in self.generators:
                    deps = [Path(self.problem.path) / d for d in self.generators[program_path]]
                    programs.append(program_type(self.problem, path, deps=deps))
                else:
                    if program_type is run.Submission:
                        programs.append(
                            program_type(self.problem, path, skip_double_build_warning=True)
                        )
                    else:
                        programs.append(program_type(self.problem, path))

            bar = ProgressBar('Build ' + program_type.subdir, items=programs)

            def build_program(p):
                localbar = bar.start(p)
                p.build(localbar)
                localbar.done()

            p = parallel.Parallel(build_program)
            for pr in programs:
                p.put(pr)
            p.done()

            bar.finalize(print_done=False)

        # TODO: Consider building all types of programs in parallel as well.
        build_programs(program.Generator, generators_used)
        build_programs(run.Submission, solutions_used)
        build_programs(program.Visualizer, visualizers_used)

        self.problem.validators(validate.InputValidator)
        self.problem.validators(validate.AnswerValidator)
        self.problem.validators(validate.OutputValidator)

        def cleanup_build_failures(t):
            if t.config.solution and t.config.solution.program is None:
                t.config.solution = None
            if not build_visualizers or (
                t.config.visualizer and t.config.visualizer.program is None
            ):
                t.config.visualizer = None

        self.root_dir.walk(cleanup_build_failures, dir_f=None)

    def add_unlisted(self):
        if not has_ryaml:
            error(
                'generate --add-unlisted needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.'
            )
            return

        unlisted = config.args.add_unlisted
        known_unlisted = {
            path
            for path in self.rules_cache
            if isinstance(path, PurePath) and path.is_relative_to(unlisted)
        }

        generators_yaml = self.problem.path / 'generators/generators.yaml'
        data = read_yaml(generators_yaml)
        if data is None:
            data = ruamel.yaml.comments.CommentedMap()

        def get_or_add(yaml, key, t=ruamel.yaml.comments.CommentedMap):
            assert isinstance(data, ruamel.yaml.comments.CommentedMap)
            if not key in yaml or yaml[key] is None:
                yaml[key] = t()
            assert isinstance(yaml[key], t)
            return yaml[key]

        parent = get_or_add(data, 'data')
        parent = get_or_add(parent, 'secret')
        entry = get_or_add(parent, 'data', ruamel.yaml.comments.CommentedSeq)

        unlisted_cases = [
            test.relative_to(self.problem.path)
            for test in (self.problem.path / unlisted).glob('*.in')
        ]
        missing_cases = [test for test in unlisted_cases if test not in known_unlisted]

        bar = ProgressBar('Add unlisted', items=missing_cases)
        for test in sorted(missing_cases, key=lambda x: x.name):
            bar.start(str(test))
            entry.append(ruamel.yaml.comments.CommentedMap())
            name = unlisted.relative_to('generators').as_posix().replace('/', '_')
            entry[-1][f'{name}_{test.stem}'] = {
                'copy': test.relative_to('generators').with_suffix('').as_posix()
            }
            bar.log('added to generators.yaml')
            bar.done()

        if len(parent['data']) == 0:
            parent['data'] = None

        write_yaml(data, generators_yaml)
        bar.finalize()
        return

    def run(self):
        self.problem.reset_testcase_hashes()

        if config.args.clean:
            self.clean_unlisted()
            return

        if config.args.clean_generated:
            self.clean_generated()
            return

        if config.args.add_unlisted:
            self.add_unlisted()
            return

        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))

        def count_dir(d):
            for name in d.includes:
                item_names.append(d.path / name)
            for name in d.unlisted_includes:
                item_names.append(d.path / name)

        self.root_dir.walk(None, count_dir)
        bar = ProgressBar('Generate', items=item_names)

        # Testcases are generated in two step:
        # 1. Generate directories and testcases listed in generators.yaml.
        #    Each directory is only started after previous directories have
        #    finished and handled by the main thread, to avoid problems with
        #    included testcases.
        # 2. Generate unlisted testcases. These come
        #    after to deduplicate them against generated testcases.

        # 1
        p = parallel.Parallel(lambda t: t.listed and t.generate(self.problem, self, bar))

        def generate_dir(d):
            p.join()
            d.generate(self.problem, self, bar)

        self.root_dir.walk(p.put, generate_dir)
        p.done()

        # 2
        p = parallel.Parallel(lambda t: not t.listed and t.generate(self.problem, self, bar))

        def generate_dir_unlisted(d):
            p.join()
            d.generate_unlisted(self.problem, self, bar)

        self.root_dir.walk(p.put, generate_dir_unlisted)
        p.done()

        bar.finalize()

        self.update_gitignore_file()

    def update_gitignore_file(self):
        gitignorefile = self.problem.path / 'data/.gitignore'

        if not self.gitignore_generated:
            # Remove existing .gitignore file if created by BAPCtools.
            if gitignorefile.is_file():
                text = gitignorefile.read_text()
                if text.startswith('# GENERATED BY BAPCtools'):
                    gitignorefile.unlink()
                    log('Deleted data/.gitignore.')
            return

        # Collect all listed testcases
        # and gitignore them in the data/ directory.
        # Sample cases are never ignored.
        # When only generating a subset of testcases, we also keep existing
        # entries not matching the filter.
        cases_to_ignore = []

        def maybe_ignore_testcase(t):
            if not (t.inline or t.sample):
                cases_to_ignore.append(t.path)

        self.root_dir.walk(maybe_ignore_testcase, None)

        if config.args.testcases and gitignorefile.is_file():
            # If there is an existing .gitignore and a list of testcases is
            # passed, keep entries that are not processed in this run.
            for line in gitignorefile.read_text().splitlines():
                if line[0] == '#' or line == '.gitignore':
                    continue
                assert line.endswith('.*')
                line = Path(line).with_suffix('')
                if not process_testcase(self.problem, line):
                    cases_to_ignore.append(line)
        cases_to_ignore.sort()

        if len(cases_to_ignore) == 0:
            return

        if gitignorefile.is_file():
            text = gitignorefile.read_text()
            if not text.startswith('# GENERATED BY BAPCtools'):
                warn('Not overwriting existing data/.gitignore file.')
                return
        else:
            text = ''

        content = '# GENERATED BY BAPCtools\n# Do not modify.\n.gitignore\n'
        for path in cases_to_ignore:
            content += path.as_posix() + '.*\n'
        if content != text:
            gitignorefile.write_text(content)
            if config.args.verbose:
                log('Updated data/.gitignore.')

    def clean_generated(self):
        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))
        bar = ProgressBar('Clean generated and cache', items=item_names)

        def clean_testcase(t):
            bar.start(str(t.path))

            # Skip cleaning unlisted cases.
            if not process_testcase(self.problem, t.path) or t.inline:
                bar.done()
                return

            infile = self.problem.path / 'data' / t.path.with_suffix(t.path.suffix + '.in')
            deleted = False
            for ext in config.KNOWN_DATA_EXTENSIONS:
                ext_file = infile.with_suffix(ext)
                if ext_file.is_file():
                    ext_file.unlink()
                    deleted = True

            if deleted:
                bar.debug('Deleting testcase')

            bar.done()

        def clean_directory(d):
            bar.start(str(d.path))

            dir_path = self.problem.path / 'data' / d.path

            if process_testcase(self.problem, d.path / 'testdata.yaml'):
                # Remove the testdata.yaml when the key is present.
                testdata_yaml_path = dir_path / 'testdata.yaml'
                if d.testdata_yaml is not None and testdata_yaml_path.is_file():
                    bar.log(f'Remove testdata.yaml')
                    testdata_yaml_path.unlink()

            if process_testcase(self.problem, d.path):
                # Try to remove the directory if it's empty.
                try:
                    dir_path.rmdir()
                    bar.log('Remove directory')
                except:
                    pass

            bar.done()

        self.root_dir.walk(clean_testcase, clean_directory, dir_last=True)
        # TODO should this be an extra command?
        if (self.problem.tmpdir / 'data').exists():
            shutil.rmtree(self.problem.tmpdir / 'data')
        bar.finalize()

    # Remove all unlisted files. Runs in dry-run mode without -f.
    def clean_unlisted(self):
        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))
        bar = ProgressBar('Clean unlisted', items=item_names)

        # Delete all files related to the testcase.
        def clean_testcase(t):
            bar.start(str(t.path))
            # Skip listed cases, but also unlisted cases in data/bad.
            if (
                not process_testcase(self.problem, t.path)
                or t.listed
                or (len(t.path.parts) > 0 and t.path.parts[0] in config.INVALID_CASE_DIRECTORIES)
            ):
                bar.done()
                return

            infile = self.problem.path / 'data' / t.path.parent / (t.path.name + '.in')
            for ext in config.KNOWN_DATA_EXTENSIONS:
                ext_file = infile.with_suffix(ext)
                if ext_file.is_file():
                    if not config.args.force:
                        bar.warn(f'Delete {ext_file.name} with -f')
                    else:
                        bar.log(f'Deleting {ext_file.name}')
                        ext_file.unlink()

            bar.done()

        # For unlisted directories, delete them entirely.
        # For listed directories, delete non-testcase files.
        def clean_directory(d):
            bar.start(str(d.path))

            path = self.problem.path / 'data' / d.path

            # Skip non existent directories
            if not path.exists():
                bar.done()
                return

            # Remove testdata.yaml when the key is not present.
            testdata_yaml_path = path / 'testdata.yaml'
            if testdata_yaml_path.is_file() and d.testdata_yaml is False:
                if not config.args.force:
                    bar.warn(f'Delete unlisted testdata.yaml with -f')
                else:
                    bar.log(f'Deleting unlisted testdata.yaml')
                    testdata_yaml_path.unlink()

            if not d.listed:
                if process_testcase(self.problem, d.path):
                    if not config.args.force:
                        bar.warn(f'Delete directory with -f')
                    else:
                        bar.log(f'Deleting directory')
                        shutil.rmtree(path)
                bar.done()
                return

            # Iterate over all files and delete if they do not belong to a testcase.
            for f in sorted(path.iterdir()):
                # Directories should be deleted in the recursive step.
                if f.is_dir():
                    continue
                # Preserve testdata.yaml in listed directories.
                if f.name == 'testdata.yaml':
                    continue
                if f.name[0] == '.':
                    continue

                relpath = f.relative_to(self.problem.path / 'data')
                if relpath.with_suffix('') in self.known_cases:
                    continue
                if relpath.with_suffix('') in self.known_directories:
                    continue

                if process_testcase(self.problem, relpath):
                    if not config.args.force:
                        bar.warn(f'Delete {f.name} with -f')
                    else:
                        bar.log(f'Deleting {f.name}')
                        f.unlink()

            bar.done()

        self.root_dir.walk(clean_testcase, clean_directory, dir_last=True)
        bar.finalize()


def generate(problem):
    config = GeneratorConfig(problem)
    if config.ok:
        config.build()
        config.run()
    return True


def cleanup_generated(problem):
    config = GeneratorConfig(problem)
    if config.ok:
        config.clean_generated()
    return True


def generated_testcases(problem):
    config = GeneratorConfig(problem)
    if config.ok:
        return config.known_cases
    return set()
