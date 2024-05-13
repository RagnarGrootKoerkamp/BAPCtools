import hashlib
import random
import io
import re
import shutil
import yaml as yamllib
import collections
import shutil
import secrets

from pathlib import Path, PurePosixPath, PurePath

import config
import inspect
import parallel
import program
import run
import validate
from testcase import Testcase
from verdicts import Verdict

from util import *


class ParseException(Exception):
    def __init__(self, message=None, path=None):
        super().__init__(message, path)
        self.message = message
        self.path = path


def assert_type(name, obj, types, path=None):
    if not isinstance(types, list):
        types = [types]
    if any(isinstance(obj, t) for t in types):
        return
    named_types = " or ".join(str(t) if t is None else t.__name__ for t in types)
    raise ParseException(
        f'{name} must be of type {named_types}, found {obj.__class__.__name__}: {obj}', path
    )


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
            raise ParseException(f'Path must not be absolute: {path}')

    if not allow_relative:
        if not path.is_absolute():
            raise ParseException(f'Path must be absolute: {path}')

    # Make all paths relative to the problem root.
    if path.is_absolute():
        return Path(*path.parts[1:])
    return Path('generators') / path


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
            raise ParseException('{seed(:[0-9]+)} may appear at most once.')

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
            result = self.program.run(
                bar, cwd, name, args=self._sub_args(seed=(seed + retry) % 2**31)
            )
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

    # Run the submission, reading testcase.in from stdin and piping stdout to testcase.ans.
    # If the .ans already exists, nothing is done
    def run(self, bar, cwd):
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

    def run_interaction(self, bar, cwd, t):
        in_path = cwd / 'testcase.in'
        interaction_path = cwd / 'testcase.interaction'
        if interaction_path.is_file():
            return True

        testcase = Testcase(self.problem, in_path, short_path=(t.path.parent / (t.name + '.in')))
        r = run.Run(self.problem, self.program, testcase)

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        ret = r.run(bar, interaction=interaction_path, submission_args=self.args)
        if ret.verdict != Verdict.ACCEPTED:
            bar.error(ret.verdict)
            return False

        return True


# Return absolute path to default submission, starting from the submissions directory.
# This function will always prints a message.
# Which submission is used is implementation defined, unless one is explicitly given on the command line.
def default_solution_path(generator_config):
    problem = generator_config.problem
    solution = None
    stored_solution = problem.tmpdir / '.default_solution'
    if config.args.default_solution:
        if generator_config.has_yaml:
            message(
                f'''--default-solution Ignored. Set the default solution in the generator.yaml!
solution: /{config.args.default_solution}''',
                'generators.yaml',
                color_type=MessageType.WARN,
            )
        else:
            solution = problem.path / config.args.default_solution
    else:
        # Use one of the accepted submissions.
        solutions = list(glob(problem.path, 'submissions/accepted/*'))
        if len(solutions) == 0:
            fatal(f'No solution specified and no accepted submissions found.')

        # always try to take the same solution to not mess with hashing
        if stored_solution.is_file():
            old_solution = Path(stored_solution.read_text().strip())
            if old_solution in solutions:
                solution = old_solution
        if solution is None:
            solution = random.choice(solutions)

        solution_short_path = solution.relative_to(problem.path / 'submissions')

        if generator_config.has_yaml:
            yaml_path = problem.path / 'generators' / 'generators.yaml'
            raw = yaml_path.read_text()
            raw = f'solution: /{solution.relative_to(problem.path)}\n' + raw
            yaml_path.write_text(raw)
            message(
                f'No solution specified. {solution_short_path} added as default solution in the generator.yaml',
                'generators.yaml',
                color_type=MessageType.LOG,
            )
        else:
            log(
                f'''No solution specified. Selected {solution_short_path}. Use
--default_solution {solution.relative_to(problem.path)}
to use a specific solution.'''
            )
    stored_solution.write_text(str(solution))
    return Path('/') / solution.relative_to(problem.path)


# A wrapper that lazily initializes the underlying SolutionInvocation on first
# usage.  This is to prevent instantiating the default solution when it's not
# actually needed.
class DefaultSolutionInvocation(SolutionInvocation):
    def __init__(self, generator_config):
        super().__init__(generator_config.problem, default_solution_path(generator_config))


KNOWN_TESTCASE_KEYS = [
    'type',
    'generate',
    'copy',
    'solution',
    'visualizer',
    'random_salt',
    'retries',
    'count',
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
KNOWN_ROOT_KEYS = ['generators', 'parallel']
DEPRECATED_ROOT_KEYS = ['gitignore_generated']


# Holds all inheritable configuration options. Currently:
# - config.solution
# - config.visualizer
# - config.random_salt
class Config:
    # Used at each directory or testcase level.

    def parse_solution(p, x, path):
        assert_type('Solution', x, [type(None), str], path)
        if x is None:
            return None
        return SolutionInvocation(p, x)

    def parse_visualizer(p, x, path):
        assert_type('Visualizer', x, [type(None), str], path)
        if x is None:
            return None
        return VisualizerInvocation(p, x)

    def parse_random_salt(p, x, path):
        assert_type('Random_salt', x, [type(None), str], path)
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
    def __init__(self, problem, generator_config, key, name: str, yaml, parent, count_index):
        assert is_testcase(yaml)

        # if not None rule will be skipped during generation
        self.parse_error = None

        # Whether this testcase is a sample.
        self.sample = len(parent.path.parts) > 0 and parent.path.parts[0] == 'sample'

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
        self.count_index = count_index

        # used to decide if this was supposed to be a duplicate or not
        self.intended_copy = self.count_index > 0

        # used to handle duplicated testcase rules
        self.copy_of = None

        if name.endswith('.in'):
            message(
                "Testcase names should not end with '.in'",
                'generators.yaml',
                parent.path / name,
                color_type=MessageType.ERROR,
            )
            name = name[:-3]

        super().__init__(problem, key, name, yaml, parent)

        # root in /data
        self.root = self.path.parts[0]
        if self.root == 'bad':
            message(
                'bad is deprecated. Use {invalid_inputs,invalid_answers} instead.',
                self.path,
                color_type=MessageType.WARN,
            )

        if not config.COMPILED_FILE_NAME_REGEX.fullmatch(name + '.in'):
            raise ParseException('Testcase does not have a valid name.')

        try:
            # files to consider for hashing
            hashes = {}
            extensions = config.KNOWN_TESTCASE_EXTENSIONS.copy()
            if self.root not in config.INVALID_CASE_DIRECTORIES[1:]:
                extensions.remove('.ans')
            if self.root not in config.INVALID_CASE_DIRECTORIES[2:]:
                extensions.remove('.out')

            if yaml is None:
                raise ParseException(
                    'Empty yaml entry (Testcases must be generated not only mentioned).'
                )
            else:
                assert_type('testcase', yaml, [str, dict])
                if isinstance(yaml, str):
                    yaml = {'generate': yaml}
                    if yaml['generate'].endswith('.in'):
                        message(
                            f"Use the new `copy: path/to/case` key instead of {yaml['generate']}.",
                            'generators.yaml',
                            self.path,
                            color_type=MessageType.WARN,
                        )
                        yaml = {'copy': yaml['generate'][:-3]}

                # checks
                if not any(x in yaml for x in ['generate', 'copy', 'in', 'interaction']):
                    raise ParseException(
                        'Testcase requires at least one key in "generate", "copy", "in", "interaction".'
                    )
                if 'submission' in yaml and 'ans' in yaml:
                    raise ParseException('Testcase cannot specify both "submissions" and "ans".')
                if 'count' in yaml and not isinstance(yaml['count'], int):
                    value = yaml['count']
                    raise ParseException(f'Testcase expected int for "count" but found {value}.')

                # 1. generate
                if 'generate' in yaml:
                    assert_type('generate', yaml['generate'], str)
                    if len(yaml['generate']) == 0:
                        raise ParseException('`generate` must not be empty.')

                    # replace count
                    command_string = yaml['generate']
                    if '{count}' in command_string:
                        if 'count' in yaml:
                            command_string = command_string.replace(
                                '{count}', f'{self.count_index+1}'
                            )
                        else:
                            message(
                                'Found {count} in generator command but no count in yaml. Ignored.',
                                self.path,
                                color_type=MessageType.WARN,
                            )
                    self.generator = GeneratorInvocation(problem, command_string)

                    # TODO: Should the seed depend on white space? For now it does, but
                    # leading and trailing whitespace is stripped.
                    seed_value = self.config.random_salt
                    if self.count_index > 0:
                        seed_value += f':{self.count_index}'
                    seed_value += self.generator.command_string.strip()
                    self.seed = int(hash_string(seed_value), 16) % 2**31
                    self.in_is_generated = True
                    self.rule['gen'] = self.generator.command_string
                    if self.generator.uses_seed:
                        self.rule['seed'] = self.seed
                        self.intended_copy = False
                    hashes['.in'] = self.generator.hash(self.seed)

                # 2. path
                if 'copy' in yaml:
                    assert_type('`copy`', yaml['copy'], str)
                    if Path(yaml['copy']).suffix in config.KNOWN_TEXT_DATA_EXTENSIONS:
                        message(
                            f"`copy: {yaml['copy']}` should not include the extension.",
                            'generators.yaml',
                            self.path,
                            color_type=MessageType.WARN,
                        )
                    self.copy = resolve_path(
                        yaml['copy'], allow_absolute=False, allow_relative=True
                    )
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
                        assert_type(ext, value, str)
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
                    raise ParseException(f'Testcase must not contain reserved key {key}.')
                if key not in KNOWN_TESTCASE_KEYS:
                    if config.args.action == 'generate':
                        message(
                            f'Unknown testcase level key: {key}',
                            'generators.yaml',
                            self.path,
                            color_type=MessageType.LOG,
                        )

            if not '.in' in hashes:
                generator_config.n_parse_error += 1
                # An error is shown during generate.
                return

            # build ordered list of hashes we want to consider
            self.hash = [hashes[ext] for ext in config.KNOWN_TESTCASE_EXTENSIONS if ext in hashes]

            # combine hashes
            if len(self.hash) == 1:
                self.hash = self.hash[0]
            else:
                self.hash = combine_hashes(self.hash)

            if self.hash in generator_config.rules_cache:
                self.copy_of = generator_config.rules_cache[self.hash]
            else:
                generator_config.rules_cache[self.hash] = self
        except ParseException as e:
            # For testcases we can handle the parse error locally since this does not influence much else
            self.parse_error = e.message
            generator_config.n_parse_error += 1

    def link(t, problem, generator_config, bar, dst):
        src_dir = problem.path / 'data' / t.path.parent
        src = src_dir / (t.name + '.in')

        for ext in config.KNOWN_DATA_EXTENSIONS:
            source = src.with_suffix(ext)
            target = dst.with_suffix(ext)
            if source.is_file() and source in generator_config.known_files:
                generator_config.known_files.add(target)
                if target.is_file():
                    if target.is_symlink() and target.resolve() == source.resolve():
                        # identical -> skip
                        pass
                    else:
                        # different -> overwrite
                        generator_config.remove(target)
                        ensure_symlink(target, source, relative=True)
                        bar.log(f'CHANGED: {target.name}')
                else:
                    # new file -> copy it
                    ensure_symlink(target, source, relative=True)
                    bar.log(f'NEW: {target.name}')
            elif target.is_file():
                # Target exists but source wasn't generated -> remove it
                generator_config.remove(target)
                bar.log(f'REMOVED: {target.name}')
            else:
                # both source and target do not exist
                pass

    def generate(t, problem, generator_config, parent_bar):
        bar = parent_bar.start(str(t.path))

        t.generate_success = False

        if t.copy_of is not None and not t.intended_copy:
            bar.warn(
                f'Found identical rule at {t.copy_of.path}. Use "count: <int>" if you want multiple identical testcases.'
            )

        # Some early checks.
        if t.copy_of is not None and not t.copy_of.generate_success:
            bar.done(False, f'See {t.copy_of.path}. Skipping.')
            return
        if t.parse_error is not None:
            bar.done(False, f'{t.parse_error} Skipping.')
            return
        if t.generator and t.generator.program is None:
            bar.done(False, f'Generator didn\'t build. Skipping.')
            return
        if t.hash is None:
            # Input can only be missing when the `copy:` does not have a corresponding `.in` file.
            # (When `generate:` or `in:` is used, the input is always present.)
            bar.done(False, f'{t.copy} does not exist. Skipping.')
            return

        target_dir = problem.path / 'data' / t.path.parent
        target_infile = target_dir / (t.name + '.in')
        target_ansfile = target_dir / (t.name + '.ans')

        # E.g. bapctmp/problem/data/<hash>.in
        cwd = problem.tmpdir / 'data' / t.hash
        cwd.mkdir(parents=True, exist_ok=True)
        infile = cwd / 'testcase.in'
        ansfile = cwd / 'testcase.ans'
        meta_path = cwd / 'meta_.yaml'

        # Returns False when some files were skipped.
        def copy_generated():
            all_done = True

            for ext in config.KNOWN_DATA_EXTENSIONS:
                source = infile.with_suffix(ext)
                target = target_infile.with_suffix(ext)

                if source.is_file():
                    generator_config.known_files.add(target)
                    if target.is_file():
                        if source.read_bytes() == target.read_bytes() and not target.is_symlink():
                            # identical -> skip
                            pass
                        else:
                            # different -> overwrite
                            generator_config.remove(target)
                            shutil.copy(source, target, follow_symlinks=True)
                            bar.log(f'CHANGED: {target.name}')
                    else:
                        # new file -> copy it
                        shutil.copy(source, target, follow_symlinks=True)
                        bar.log(f'NEW: {target.name}')
                elif target.is_file():
                    # Target exists but source wasn't generated -> remove it
                    generator_config.remove(target)
                    bar.log(f'REMOVED: {target.name}')
                else:
                    # both source and target do not exist
                    pass
            return all_done

        if t.copy_of is not None:
            if t.intended_copy:
                # This was generated by count: so we can simply link
                t.copy_of.link(problem, generator_config, bar, target_infile)
            else:
                # This is a duplicated rule, we copy to show this
                copy_generated()
            t.generate_success = True
            bar.done(message='SKIPPED: up to date')
            return

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

            if not infile.is_file():
                return (False, False)
            if not ansfile.is_file():
                return (False, False)
            if (
                (problem.interactive or problem.multipass)
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
            for h in testcase.validator_hashes(validate.InputValidator, bar):
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

        def add_testdata_to_cache():
            # Used to identify generated testcases
            generator_config.hashed_in.add(hash_file_content(infile))

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
                    if result.err is not None:
                        bar.debug('generator:', result.err)
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

                # Step 4: copy the source file.
                if not infile.is_file():
                    # Step 4b: Error if infile was not generated.
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
                    if problem.interactive or problem.multipass:
                        if not testcase.ans_path.is_file():
                            testcase.ans_path.write_text('')
                        # For interactive/multi-pass problems, run the solution and generate a .interaction.
                        if (
                            t.config.solution
                            and (testcase.root == 'sample' or config.args.interaction)
                            and '.interaction' not in t.hardcoded
                        ):
                            if not t.config.solution.run_interaction(bar, cwd, t):
                                return
                    else:
                        # Generate a .ans if not already generated by earlier steps.
                        if not testcase.ans_path.is_file():
                            # Run the solution if available.
                            if t.config.solution:
                                if not t.config.solution.run(bar, cwd).status:
                                    return
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

                # Generate visualization
                if not config.args.no_visualizer and t.config.visualizer:
                    # Note that the .in/.ans are generated even when the visualizer fails.
                    t.config.visualizer.run(bar, cwd, infile.stem)

                check_deterministic(True)

            meta_yaml['cache_data'] = t.cache_data
            if generator_up_to_date:
                hashes = testcase.validator_hashes(validate.InputValidator, bar)
                for h in hashes:
                    meta_yaml['validator_hashes'][h] = hashes[h]
            else:
                meta_yaml['validator_hashes'] = testcase.validator_hashes(
                    validate.InputValidator, bar
                )

            # Update metadata
            if copy_generated():
                write_yaml(meta_yaml, meta_path.open('w'), allow_yamllib=True)
            message = ''
        else:
            if config.args.action != 'generate':
                bar.logged = True  # Disable redundant 'up to date' message in run mode.
            check_deterministic(False)
            message = 'SKIPPED: up to date'
            copy_generated()

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
    def __init__(self, problem, key, name: str, yaml: dict = None, parent=None):
        assert is_directory(yaml)

        # The root Directory object has name ''.
        if not isinstance(parent, RootDirectory):
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(name):
                raise ParseException(f'Directory does not have a valid name.', parent.path / name)

        super().__init__(problem, key, name, yaml, parent)

        if name == '':
            for key in yaml:
                if key in RESERVED_DIRECTORY_KEYS:
                    raise ParseException(
                        f'Directory must not contain reserved key {key}.', self.path
                    )
                if key in DEPRECATED_ROOT_KEYS:
                    message(
                        f'Dreprecated root level key: {key}, ignored',
                        'generators.yaml',
                        self.path,
                        color_type=MessageType.WARN,
                    )
                elif key not in KNOWN_DIRECTORY_KEYS + KNOWN_ROOT_KEYS:
                    if config.args.action == 'generate':
                        message(
                            f'Unknown root level key: {key}',
                            'generators.yaml',
                            self.path,
                            color_type=MessageType.LOG,
                        )
        else:
            for key in yaml:
                if key in RESERVED_DIRECTORY_KEYS + KNOWN_ROOT_KEYS:
                    raise ParseException(
                        f'Directory must not contain reserved key {key}.', self.path
                    )
                if key not in KNOWN_DIRECTORY_KEYS:
                    if config.args.action == 'generate':
                        message(
                            f'Unknown directory level key: {key}',
                            'generators.yaml',
                            self.path,
                            color_type=MessageType.LOG,
                        )

        if 'testdata.yaml' in yaml:
            self.testdata_yaml = yaml['testdata.yaml']
        else:
            self.testdata_yaml = False

        self.numbered = False

        # List of child TestcaseRule/Directory objects, filled by parse().
        self.data = []
        # Map of short_name => TestcaseRule, filled by parse().
        self.includes = dict()

        # Sanity checks for possibly empty data.
        if 'data' not in yaml:
            return
        data = yaml['data']
        if data is None:
            return
        if data == '':
            return
        assert_type('Data', data, [dict, list])

        if isinstance(data, dict):
            yaml['data'] = [data]
            data = yaml['data']
        else:
            self.numbered = True
            if len(data) == 0:
                return

            for d in data:
                assert_type('Numbered case', d, dict)
                if len(d) != 1:
                    if 'in' in d or 'ans' in d or 'copy' in d:
                        raise ParseException(
                            'Dictionary must contain exactly one named testcase/group.\nTo specify hardcoded in/ans/copy, indent one more level.',
                            self.path,
                        )
                    else:
                        raise ParseException(
                            'Dictionary must contain exactly one named testcase/group.',
                            self.path,
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
        if d.testdata_yaml:
            generator_config.known_files.add(testdata_yaml_path)
            yaml_text = yamllib.dump(dict(d.testdata_yaml))

            if testdata_yaml_path.is_file():
                if yaml_text == testdata_yaml_path.read_text():
                    # identical -> skip
                    pass
                else:
                    # different -> overwrite
                    generator_config.remove(testdata_yaml_path)
                    testdata_yaml_path.write_text(yaml_text)
                    bar.log(f'CHANGED: testdata.yaml')
            else:
                # new file -> create it
                testdata_yaml_path.write_text(yaml_text)
                bar.log(f'NEW: testdata.yaml')
        elif d.testdata_yaml == '' and testdata_yaml_path.is_file():
            # empty -> remove it
            generator_config.remove(testdata_yaml_path)
            bar.log(f'REMOVED: testdata.yaml')
        bar.done()

    def generate_includes(d, problem, generator_config, bar):
        for key in d.includes:
            t = d.includes[key]
            target = t.path
            new_case = d.path / target.name
            bar.start(str(new_case))
            infile = problem.path / 'data' / target.parent / (target.name + '.in')
            new_infile = problem.path / 'data' / d.path / (target.name + '.in')

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
            hashes = testcase.validator_hashes(validate.InputValidator, bar)

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
            t.link(problem, generator_config, bar, new_infile)
            bar.done()


# Returns the numbered name
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
        assert_type('Generators', generators_yaml, dict)
        generators = {}
        for gen in generators_yaml:
            if (
                gen.startswith('/')
                or Path(gen).is_absolute()
                or not config.COMPILED_FILE_NAME_REGEX.fullmatch(gen + '.x')
            ):
                raise ParseException('Invalid generator name', f'generators/{gen}')

            path = Path('generators') / gen

            deps = generators_yaml[gen]
            assert_type('Generator dependencies', deps, list)
            if len(deps) == 0:
                raise ParseException('Generator dependencies must not be empty.', path)
            for d in deps:
                assert_type('Generator dependencies', d, str)

            generators[path] = [Path('generators') / d for d in deps]
        return generators

    # Only used at the root directory level.
    ROOT_KEYS = [
        ('generators', {}, parse_generators),
    ]

    # Parse generators.yaml.
    def __init__(self, problem, restriction=None):
        self.problem = problem
        yaml_path = self.problem.path / 'generators' / 'generators.yaml'
        self.n_parse_error = 0

        # A map of paths `secret/testgroup/testcase` to their canonical TestcaseRule.
        # For generated cases this is the rule itself.
        # For included cases, this is the 'resolved' location of the testcase that is included.
        self.known_cases = dict()
        # A set of paths `secret/testgroup`.
        self.known_directories = set()
        # Used for cleanup
        self.known_files = set()
        # A map from key to (is_included, list of testcases and directories),
        # used for `include` statements.
        self.known_keys = collections.defaultdict(lambda: [False, []])
        # A set of testcase rules, including seeds.
        self.rules_cache = dict()
        # The set of generated testcases keyed by hash(testdata).
        self.generated_testdata = dict()
        # Path to the trash directory for this run
        self.trashdir = None
        # Set of hash(.in) for all generated testcases
        self.hashed_in = set()
        # Files that should be processed
        self.restriction = restriction

        if yaml_path.is_file():
            yaml = read_yaml(yaml_path, plain=True)
            self.has_yaml = True
        else:
            yaml = None
            self.has_yaml = False

        try:
            self.parse_yaml(yaml)
        except ParseException as e:
            # Handle fatal parse errors
            message(e.message, 'generators.yaml', e.path, color_type=MessageType.ERROR)
            exit()

    # testcase_short_path: secret/1.in
    def process_testcase(self, relative_testcase_path):
        if not self.restriction:
            return True
        absolute_testcase_path = self.problem.path / 'data' / relative_testcase_path.with_suffix('')
        for p in self.restriction:
            for basedir in get_basedirs(self.problem, 'data'):
                if is_relative_to(basedir / p, absolute_testcase_path):
                    return True
        return False

    def parse_yaml(self, yaml):
        assert_type('Root yaml', yaml, [type(None), dict])
        if yaml is None:
            yaml = dict()

        # Read root level configuration
        for key, default, func in GeneratorConfig.ROOT_KEYS:
            if yaml and key in yaml:
                setattr(self, key, func(yaml[key] if yaml[key] is not None else default))
            else:
                setattr(self, key, default)

        def add_known(obj):
            path = obj.path
            name = path.name
            if isinstance(obj, TestcaseRule):
                self.known_cases[path] = obj
            elif isinstance(obj, Directory):
                self.known_directories.add(path)
            else:
                assert False

            key = self.known_keys[obj.key]
            key[1].append(obj)
            if key[0] and len(key[1]) == 2:
                message(
                    f'Included key {name} exists more than once as {key[1][0].path} and {key[1][1].path}.',
                    'generators.yaml',
                    obj.path,
                    color_type=MessageType.ERROR,
                )

        num_numbered_testcases = 0
        testcase_id = 0

        def parse_count(yaml, warn_for=None):
            if yaml is None or 'count' not in yaml or not isinstance(yaml['count'], int):
                return 1
            count = yaml['count']
            if count < 1:
                if warn_for is not None:
                    message(
                        f'Found count: {count}, increased to 1.',
                        'generators.yaml',
                        warn_for,
                        color_type=MessageType.WARN,
                    )
                return 1
            if count > 100:
                if warn_for is not None:
                    message(
                        f'Found count: {count}, limited to 100.',
                        'generators.yaml',
                        warn_for,
                        color_type=MessageType.WARN,
                    )
                return 100
            return count

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
                            num_numbered_testcases += parse_count(elem[key])
                        elif is_directory(elem[key]):
                            count(elem[key])

        count(yaml)

        # Main recursive parsing function.
        # key: the yaml key e.g. 'testcase'
        # name_gen: each call should result in the next (possibly numbered) name e.g. '01-testcase'
        # Returns either a single Rule or a list of Rules
        def parse(key, name_gen, yaml, parent):
            name = name_gen()
            assert_type('Testcase/directory', yaml, [type(None), str, dict], parent.path)
            if not is_testcase(yaml) and not is_directory(yaml):
                raise ParseException(f'not parsed as a testcase or directory.', parent.path / name)

            if is_testcase(yaml):
                if isinstance(parent, RootDirectory):
                    raise ParseException(f'Testcase must be inside Directory', name)

                count = parse_count(yaml, parent.path / name)

                ts = []
                for count_index in range(count):
                    if count_index > 0:
                        name = name_gen()
                    if 'count' in yaml:
                        name += f'-{count_index+1:0{len(str(count))}}'

                    # If a list of testcases was passed and this one is not in it, skip it.
                    if not self.process_testcase(parent.path / name):
                        continue

                    t = TestcaseRule(self.problem, self, key, name, yaml, parent, count_index)
                    if t.path in self.known_cases:
                        message(
                            f'was already parsed. Skipping.',
                            'generators.yaml',
                            t.path,
                            color_type=MessageType.ERROR,
                        )
                        continue

                    add_known(t)
                    ts.append(t)
                return ts

            assert is_directory(yaml)

            d = Directory(self.problem, key, name, yaml, parent)
            if d.path in self.known_cases or d.path in self.known_directories:
                raise ParseException('Duplicate entry', d.path)
            add_known(d)

            # Parse child directories/testcases.
            if 'data' in yaml and yaml['data']:
                # Count the number of child testgroups.
                num_testgroups = 0
                for dictionary in d.data:
                    assert_type('Elements of data', dictionary, dict, d.path)
                    for child_name, child_yaml in sorted(dictionary.items()):
                        if is_directory(child_yaml):
                            num_testgroups += 1

                testgroup_id = 0
                for dictionary in yaml['data']:
                    for key in dictionary:
                        assert_type('Testcase/directory name', key, [type(None), str], d.path)

                    # Process named children alphabetically, but not in the root directory.
                    # There, process in the 'natural order'.
                    order = [
                        'sample',
                        'secret',
                        'invalid_outputs',
                        'invalid_answers',
                        'invalid_inputs',
                    ]
                    keys = dictionary.keys()
                    if isinstance(parent, RootDirectory):
                        keys = sorted(
                            keys,
                            key=lambda k: (order.index(k), k) if k in order else (999, k),
                        )
                    else:
                        keys = sorted(keys)

                    for child_key in keys:
                        child_yaml = dictionary[child_key]
                        if d.numbered:
                            if is_directory(child_yaml):

                                def next_testgroup_name():
                                    nonlocal testgroup_id
                                    testgroup_id += 1
                                    return numbered_testcase_name(
                                        child_key, testgroup_id, num_testgroups
                                    )

                                child_name = next_testgroup_name
                            elif is_testcase(child_yaml):

                                def next_testcase_name():
                                    nonlocal testcase_id
                                    testcase_id += 1
                                    return numbered_testcase_name(
                                        child_key, testcase_id, num_numbered_testcases
                                    )

                                child_name = next_testcase_name
                            else:
                                # Use error will be given inside parse(child).
                                child_name = lambda: ''

                        else:
                            child_name = lambda: child_key
                            if not child_name():
                                raise ParseException(
                                    'Unnumbered testcases must not have an empty key',
                                    d.path,
                                )
                        c = parse(child_key, child_name, child_yaml, d)
                        if isinstance(c, list):
                            d.data.extend(c)
                        elif c is not None:
                            d.data.append(c)

            # Include TestcaseRule t for the current directory.
            def add_included_case(t):
                target = t.path
                name = target.name
                p = d.path / name
                if p in self.known_cases:
                    if target != self.known_cases[p].path:
                        if self.known_cases[p].path == p:
                            message(
                                f'conflict with included case {target}.',
                                'generators.yaml',
                                p,
                                color_type=MessageType.ERROR,
                            )
                        else:
                            message(
                                f'included with multiple targets {target} and {self.known_cases[p].path}.',
                                'generators.yaml',
                                p,
                                color_type=MessageType.ERROR,
                            )
                    return
                self.known_cases[p] = t
                d.includes[name] = t

            if 'include' in yaml:
                assert_type('includes', yaml['include'], list, d.path)

                for include in yaml['include']:
                    assert_type('include', include, str, d.path)
                    if '/' in include:
                        message(
                            f'Include {include} should be a testcase/testgroup key, not a path.',
                            'generators.yaml',
                            d.path,
                            color_type=MessageType.ERROR,
                        )
                        continue

                    if include in self.known_keys:
                        key = self.known_keys[include]
                        if len(key[1]) != 1:
                            message(
                                f'Included key {include} exists more than once.',
                                'generators.yaml',
                                d.path,
                                color_type=MessageType.ERROR,
                            )
                            continue

                        key[0] = True
                        obj = key[1][0]
                        if isinstance(obj, TestcaseRule):
                            add_included_case(obj)
                        else:
                            obj.walk(
                                add_included_case,
                                lambda d: [add_included_case(t) for t in d.includes.values()],
                            )
                            pass
                    else:
                        message(
                            f'Unknown include key {include} does not refer to a previous testcase.',
                            'generators.yaml',
                            d.path,
                            color_type=MessageType.ERROR,
                        )
                        continue
            return d

        self.root_dir = parse('', lambda: '', yaml, RootDirectory())

    def build(self, build_visualizers=True):
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

            parallel.run_tasks(build_program, programs)

            bar.finalize(print_done=False)

        # TODO: Consider building all types of programs in parallel as well.
        build_programs(program.Generator, generators_used)
        build_programs(run.Submission, solutions_used)
        build_programs(program.Visualizer, visualizers_used)

        self.problem.validators(validate.InputValidator)
        if not self.problem.interactive and not self.problem.multipass:
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

    def run(self):
        self.update_gitignore_file()
        self.problem.reset_testcase_hashes()

        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))

        def count_dir(d):
            for name in d.includes:
                item_names.append(d.path / name)

        self.root_dir.walk(None, count_dir)
        bar = ProgressBar('Generate', items=item_names)

        # Testcases are generated in two steps:
        # 1. Generate directories and unique testcases listed in generators.yaml.
        # 2. Generate duplicates of known testcases. All directories should already exists
        #    Each directory is only started after previous directories have
        #    finished and handled by the main thread, to avoid problems with
        #    included testcases.

        # 1
        p = parallel.new_queue(lambda t: t.copy_of is None and t.generate(self.problem, self, bar))

        def generate_dir(d):
            p.join()
            d.generate(self.problem, self, bar)

        self.root_dir.walk(p.put, generate_dir)
        p.done()

        # 2
        p = parallel.new_queue(
            lambda t: t.copy_of is not None and t.generate(self.problem, self, bar)
        )

        def generate_copies_and_includes(d):
            p.join()
            d.generate_includes(self.problem, self, bar)

        self.root_dir.walk(p.put, generate_copies_and_includes)
        p.done()

        bar.finalize()

    # move a file or into the trash directory
    def remove(self, src):
        if self.trashdir is None:
            self.trashdir = self.problem.tmpdir / 'trash' / secrets.token_hex(4)
        dst = self.trashdir / src.absolute().relative_to((self.problem.path / 'data').absolute())
        dst.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(src, dst)

    def _remove_unknown(self, path, bar, silent=False):
        local = path.relative_to(self.problem.path / 'data')
        keep = any(
            (
                path.is_dir() and local in self.known_directories,
                not path.is_dir() and path in self.known_files,
                not path.is_dir() and not self.process_testcase(local),
            )
        )
        if keep:
            if path.is_dir():
                # specially handle known .in files to reduce output noice
                for f in sorted(path.glob('*.in')):
                    if f.is_file() and hash_file_content(f) in self.hashed_in:
                        for ext in config.KNOWN_TEXT_DATA_EXTENSIONS:
                            tmp = f.with_suffix(ext)
                            if tmp.is_file():
                                self._remove_unknown(f.with_suffix(ext), bar, True)
                for f in sorted(path.glob('*')):
                    self._remove_unknown(f, bar)
        else:
            self.remove(path)
            if silent:
                bar.debug(f'REMOVED: {path.name}')
            else:
                bar.log(f'REMOVED: {path.name}')

    # remove all files in data that were not written by the during run
    def clean_up(self):
        bar = ProgressBar('Clean Up', max_len=-1)

        self._remove_unknown(self.problem.path / 'data', bar)
        if self.trashdir is not None:
            bar.warn('Some files were changed/removed.', f'-> {self.trashdir}')
        bar.finalize()

    # write a gitignore file to ignore everything in data/ except data/sample/
    def update_gitignore_file(self):
        gitignorefile = self.problem.path / '.gitignore'

        content = """#GENERATED BY BAPCtools
data/*
!data/sample/
"""

        if gitignorefile.is_file():
            # if there is any rule for data/ we expect that the user knows
            # what he does.
            if 'data/' not in gitignorefile.read_text():
                with gitignorefile.open("a") as f:
                    f.write('\n')
                    f.write(content)
                log('Updated .gitignore.')
        else:
            assert not gitignorefile.exists()
            gitignorefile.write_text(content)
            log('Created .gitignore.')

    # add all testcases specified as copy keys in the generators.yaml
    # can handle files and complete directories
    def add(self, to_add):
        if not has_ryaml:
            error(
                'generate --add needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.'
            )
            return

        in_files = []
        for path in to_add:
            if path.suffix == '.in':
                in_files.append(path)
            else:
                in_files += [
                    test.relative_to(self.problem.path)
                    for test in (self.problem.path / path).glob('*.in')
                ]

        known = {
            rule.copy.relative_to(self.problem.path)
            for rule in self.known_cases.values()
            if rule.copy is not None and rule.copy.is_relative_to(self.problem.path)
        }

        generators_yaml = self.problem.path / 'generators' / 'generators.yaml'
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

        bar = ProgressBar('Adding', items=in_files)
        for in_file in sorted(in_files, key=lambda x: x.name):
            bar.start(str(in_file))
            if not (self.problem.path / in_file).exists():
                bar.warn('file not found. Skipping.')
            elif in_file in known:
                bar.log('already found in generators.yaml. Skipping.')
            else:
                entry.append(ruamel.yaml.comments.CommentedMap())
                path_in_gen = in_file.relative_to('generators')
                name = path_in_gen.as_posix().replace('/', '_')
                new = ruamel.yaml.comments.CommentedMap(
                    {'copy': path_in_gen.with_suffix('').as_posix()}
                )
                new.fa.set_flow_style()
                entry[-1][f'{name}_{in_file.stem}'] = new
                bar.log('added to generators.yaml.')
            bar.done()

        if len(parent['data']) == 0:
            parent['data'] = None

        write_yaml(data, generators_yaml)
        bar.finalize()
        return


# Delete files in the tmpdir trash directory. By default all files older than 10min are removed
# and additionally the oldest files are removed until the trash is less than 1 GiB
def clean_trash(problem, time_limit=10 * 60, size_lim=1024 * 1024 * 1024):
    trashdir = problem.tmpdir / 'trash'
    if trashdir.exists():
        dirs = [(d, path_size(d)) for d in trashdir.iterdir()]
        dirs.sort(key=lambda d: d[0].stat().st_mtime)
        total_size = sum(x for d, x in dirs)
        time_limit = time.time() - time_limit
        for d, x in dirs:
            if x == 0 or total_size > size_lim or d.stat().st_mtime < time_limit:
                total_size -= x
                shutil.rmtree(d)


# Clean data/ and tmpdir/data/
def clean_data(problem, data=True, cache=True):
    dirs = [
        problem.path / 'data' if data else None,
        problem.tmpdir / 'data' if cache else None,
    ]
    for d in dirs:
        if d is not None and d.exists():
            shutil.rmtree(d)


def generate(problem):
    clean_trash(problem)

    if config.args.clean:
        clean_data(problem, True, True)
        return True

    gen_config = GeneratorConfig(problem, config.args.testcases)

    if config.args.add is not None:
        gen_config.add(config.args.add)
        return True

    if config.args.action == 'generate':
        if not gen_config.has_yaml:
            error('Did not find generators/generators.yaml')
            return True

    if gen_config.has_yaml:
        gen_config.build()
        gen_config.run()
        gen_config.clean_up()
    return True


def testcases(problem, symlinks=False):
    gen_config = GeneratorConfig(problem)
    if gen_config.has_yaml:
        if symlinks:
            return {
                problem.path / 'data' / p.parent / (p.name + '.in')
                for p, x in gen_config.known_cases.items()
                if x.parse_error is None
            }
        else:
            return {
                (problem.path / 'data' / x.path).with_suffix('.in')
                for x in gen_config.known_cases.values()
                if x.parse_error is None and not x.intended_copy
            }
    else:
        testcases = set(problem.path.glob('data/**/*.in'))
        if not symlinks:
            testcases = {t for t in testcases if not t.is_symlink()}
        return testcases
