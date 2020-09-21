import hashlib
import random
import re
import shutil
import yaml as yamllib
import queue
import threading
import signal

from pathlib import Path

import config
import program
import validate
import run

from util import *
from problem import Problem


def check_type(name, obj, types, path=None):
    if not isinstance(types, list): types = [types]
    if obj is None:
        if obj in types: return
    else:
        if obj.__class__ in types: return
    named_types = " or ".join(str(t) if t is None else t.__name__ for t in types)
    if path:
        fatal(
            f'{name} must be of type {named_types}, found {obj.__class__.__name__} at {path}: {obj}'
        )
    else:
        fatal(f'{name} must be of type {named_types}, found {obj.__class__.__name__}: {obj}')


def is_testcase(yaml):
    return yaml == None or isinstance(
        yaml, str) or (isinstance(yaml, dict) and 'input' in yaml
                       and not ('type' in yaml and yaml['type'] != 'testcase'))


def is_directory(yaml):
    return isinstance(yaml, dict) and 'type' in yaml and yaml['type'] == 'directory'


# Returns the given path relative to the problem root.
def resolve_path(path, *, allow_absolute, allow_relative):
    assert isinstance(path, str)
    path = Path(path)
    if not allow_absolute:
        if path.is_absolute():
            fatal(f'Path must not be absolute: {path}')

    if not allow_relative:
        if not path.is_absolute():
            fatal(f'Path must be absolute: {path}')

    # Make all paths relative to the problem root.
    if path.is_absolute(): return Path(*path.parts[1:])
    return Path('generators') / path


# testcase_short_path: secret/1.in
def process_testcase(problem, testcase_path):
    if not getattr(config.args, 'testcases', None): return True
    for p in config.args.testcases:
        # Try the given path itself, and the given path without the last suffix.
        for p2 in [p, p.with_suffix('')]:
            try:
                testcase_path.relative_to(problem.path / p2)
                return True
            except ValueError:
                pass
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

        # The original command string, used for caching invocation results.
        self.command_string = string

        # The name of the program to be executed, relative to the problem root.
        self.program_path = resolve_path(command,
                                         allow_absolute=allow_absolute,
                                         allow_relative=allow_relative)

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
        if seed: command_string = self.SEED_REGEX.sub(str(seed), command_string)
        return command_string

    # Return the full command to be executed.
    def _sub_args(self, *, name, seed=None):
        if self.uses_seed:
            assert seed is not None

        def sub(arg):
            if name: arg = self.NAME_REGEX.sub(str(name), arg)
            if self.uses_seed: arg = self.SEED_REGEX.sub(str(seed), arg)
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
            result = self.program.run(bar,
                                      cwd,
                                      name,
                                      args=self._sub_args(name=name, seed=seed + retry))
            if result.ok is True:
                break
            if not result.retry:
                break

        if result.ok is not True:
            if retries > 1:
                bar.error(f'Failed {retry+1} times', result.err)
            else:
                bar.error(f'Failed', result.err)

        if result.ok is True and config.args.error and result.err:
            bar.log('stderr', result.err)

        return result


class VisualizerInvocation(Invocation):
    def __init__(self, problem, string):
        super().__init__(problem, string, allow_absolute=True, allow_relative=False)

    # Run the visualizer, taking {name} as a command line argument.
    # Stdin and stdout are not used.
    def run(self, bar, cwd, name):
        result = self.program.run(cwd, args=self._sub_args(name=name))

        if result.ok == -9:
            bar.error(f'TIMEOUT after {timeout}s')
        elif result.ok is not True:
            bar.error('Failed', result.err)

        if result.ok is True and config.args.error and result.err:
            bar.log('stderr', result.err)
        return result


class SolutionInvocation(Invocation):
    def __init__(self, problem, string):
        super().__init__(problem, string, allow_absolute=True, allow_relative=False)

    # Run the submission, reading {name}.in from stdin and piping stdout to {name}.ans.
    # If the .ans already exists, nothing is done
    def run(self, bar, cwd, name):
        in_path = cwd / (name + '.in')
        ans_path = cwd / (name + '.ans')

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        result = self.program.run(in_path, ans_path, args=self.args, cwd=cwd)

        if result.ok == -9:
            bar.error(f'solution TIMEOUT after {result.duration}s')
        elif result.ok is not True:
            bar.error('Failed', result.err)

        if result.ok is True and config.args.error and result.err:
            bar.log('stderr', result.err)
        return result

    def run_interactive(self, problem, bar, cwd, t):
        in_path = cwd / (t.name + '.in')
        interaction_path = cwd / (t.name + '.interaction')
        if interaction_path.is_file(): return True

        testcase = run.Testcase(problem, in_path, short_path=t.path / t.name)
        r = run.Run(problem, self.program, testcase)

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        ret = r.run(interaction=interaction_path, submission_args=self.args)
        if ret.verdict != 'ACCEPTED':
            bar.error(ret.verdict)
            return False

        return True


KNOWN_TESTCASE_KEYS = ['type', 'input', 'solution', 'visualizer', 'random_salt', 'retries']
RESERVED_TESTCASE_KEYS = ['data', 'testdata.yaml', 'include']
KNOWN_DIRECTORY_KEYS = [
    'type', 'data', 'testdata.yaml', 'include', 'solution', 'visualizer', 'random_salt', 'retries'
]
RESERVED_DIRECTORY_KEYS = ['input']
KNOWN_ROOT_KEYS = ['generators', 'parallel', 'gitignore_generated']


# Holds all inheritable configuration options. Currently:
# - config.solution
# - config.visualizer
# - config.random_salt
class Config:
    # Used at each directory or testcase level.
    def parse_solution(p, x, path):
        check_type('Solution', x, [None, str], path)
        if x is None: return None
        return SolutionInvocation(p, x)

    def parse_visualizer(p, x, path):
        check_type('Visualizer', x, [None, str], path)
        if x is None: return None
        return VisualizerInvocation(p, x)

    def parse_random_salt(p, x, path):
        check_type('Random_salt', x, [None, str], path)
        if x is None: return ''
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
            if func is None: func = lambda p, x, path: x
            if yaml and key in yaml:
                setattr(self, key, func(problem, yaml[key], path))
            elif parent_config is not None:
                setattr(self, key, getattr(parent_config, key))
            else:
                setattr(self, key, default)


class Rule:
    def __init__(self, problem, name, yaml, parent):
        assert parent is not None

        if isinstance(yaml, dict):
            self.config = Config(problem, parent.path / name, yaml, parent_config=parent.config)
        else:
            self.config = parent.config

        # Directory key of the current directory/testcase.
        self.name = name
        # Path of the current directory/testcase relative to data/.
        self.path: Path = parent.path / self.name


class TestcaseRule(Rule):
    def __init__(self, problem, name: str, yaml, parent, *, tracked=True):
        assert is_testcase(yaml)
        assert config.COMPILED_FILE_NAME_REGEX.fullmatch(name + '.in')

        if name.endswith('.in'):
            error(f'Testcase names should not end with \'.in\': {parent.path / name}')
            name = name[:-3]

        self.manual = False
        self.manual_inline = False
        self.tracked = tracked

        if isinstance(yaml, str) and len(yaml) == 0:
            fatal(
                f'Manual testcase should be None or a relative path, not empty string at {parent.path/name}.'
            )

        if yaml is None:
            self.manual = True
            self.manual_inline = True
            yaml = {'input': Path('data') / parent.path / (name + '.in')}
        elif isinstance(yaml, str) and yaml.endswith('.in'):
            self.manual = True
            yaml = {'input': resolve_path(yaml, allow_absolute=False, allow_relative=True)}
        elif isinstance(yaml, str):
            yaml = {'input': yaml}
        elif isinstance(yaml, dict):
            assert 'input' in yaml
            check_type('Input', yaml['input'], [None, str])
        else:
            assert False

        super().__init__(problem, name, yaml, parent)

        for key in yaml:
            if key in RESERVED_TESTCASE_KEYS:
                fatal('Testcase must not contain reserved key {key}.')
            if key not in KNOWN_TESTCASE_KEYS:
                log(f'Unknown testcase level key: {key} in {self.path}')

        inpt = yaml['input']

        if self.manual:
            self.source = inpt
        else:
            # TODO: Should the seed depend on white space? For now it does.
            seed_value = self.config.random_salt + inpt
            self.seed = int(hashlib.sha512(seed_value.encode('utf-8')).hexdigest(), 16) % (2**31)
            self.generator = GeneratorInvocation(problem, inpt)

        key = (inpt, self.config.random_salt)
        if key in problem._rules_cache:
            fatal(f'Found duplicate rule "{inpt}" at {problem._rules_cache[key]} and {self.path}')
        problem._rules_cache[key] = self.path

    def generate(t, problem, generator_config, parent_bar):
        bar = parent_bar.start(str(t.path))

        # E.g. bapctmp/problem/data/secret/1.in
        cwd = problem.tmpdir / 'data' / t.path
        cwd.mkdir(parents=True, exist_ok=True)
        infile = cwd / (t.name + '.in')
        ansfile = cwd / (t.name + '.ans')
        meta_path = cwd / 'meta_.yaml'

        target_dir = problem.path / 'data' / t.path.parent
        target_infile = target_dir / (t.name + '.in')
        target_ansfile = target_dir / (t.name + '.ans')

        if not t.manual and t.generator.program is None:
            bar.done(False, f'Generator didn\'t build.')
            return

        if t.manual and not (problem.path / t.source).is_file():
            bar.done(False, f'Source for manual case not found: {t.source}')
            return

        if t.manual and t.manual_inline and t.tracked:
            if config.args.move_manual:
                reltarget = config.args.move_manual.relative_to((problem.path).resolve())
                bar.log(f'Moving {t.path} to {reltarget}.')
                generator_config.tracked_inline_manual.add(t.path)
            else:
                bar.debug(f'Move inline manual case using --move-manual.')

        # For each generated .in file, both new and up to date, check that they
        # use a deterministic generator by rerunning the generator with the
        # same arguments.  This is done when --check-deterministic is passed,
        # which is also set to True when running `bt all`.
        # This doesn't do anything for manual cases.
        # It also checks that the input changes when the seed changes.
        def check_deterministic():
            if not getattr(config.args, 'check_deterministic', False):
                return

            if t.manual:
                return

            # Check that the generator is deterministic.
            # TODO: Can we find a way to easily compare cpython vs pypy? These
            # use different but fixed implementations to hash tuples of ints.
            result = t.generator.run(bar, cwd, t.name, t.seed, t.config.retries)
            if result.ok is not True:
                return

            # This is checked when running the generator.
            assert infile.is_file()

            # If this doesn't exist, the testcase wasn't up to date, so must have been generated already.
            assert target_infile.is_file()

            # Now check that the source and target are equal.
            if infile.read_bytes() == target_infile.read_bytes():
                bar.part_done(True, 'Generator is deterministic.')
            else:
                bar.part_done(False,
                              f'Generator `{t.generator.command_string}` is not deterministic.')

            # If {seed} is used, check that the generator depends on it.
            if t.generator.uses_seed:
                depends_on_seed = False
                for run in range(config.SEED_DEPENDENCY_RETRIES):
                    new_seed = (t.seed + 1 + run) % (2**31)
                    result = t.generator.run(bar, cwd, t.name, new_seed, t.config.retries)
                    if result.ok is not True:
                        return

                    # Now check that the source and target are different.
                    if infile.read_bytes() != target_infile.read_bytes():
                        depends_on_seed = True
                        break

                if depends_on_seed:
                    bar.debug('Generator depends on seed.')
                else:
                    bar.warn(
                        f'Generator `{t.generator.command_string}` likely does not depend on seed:',
                        f'All values in [{t.seed}, {new_seed}] give the same result.')

        # The expected contents of the meta_ file.
        def up_to_date():
            # The testcase is up to date if:
            # - both target infile ans ansfile exist
            # - meta_ exists with a timestamp newer than the 3 Invocation timestamps (Generator/Submission/Visualizer).
            # - meta_ exists with a timestamp newer than target infile ans ansfile
            # - meta_ contains exactly the right content
            #
            # Use generate --all to skip this check.

            last_change = 0
            t.cache_data = {}
            if t.manual:
                last_change = max(last_change, (problem.path / t.source).stat().st_mtime)
                t.cache_data['source'] = str(t.source)
            else:
                last_change = max(last_change, t.generator.program.timestamp)
                t.cache_data['generator'] = t.generator.cache_command(seed=t.seed)
            if t.config.solution:
                last_change = max(last_change, t.config.solution.program.timestamp)
                t.cache_data['solution'] = t.config.solution.cache_command()
            if t.config.visualizer:
                last_change = max(last_change, t.config.visualizer.program.timestamp)
                t.cache_data['visualizer'] = t.config.visualizer.cache_command()

            if hasattr(config.args, 'all') and config.args.all is True:
                return False

            if not target_infile.is_file(): return False
            if not target_ansfile.is_file(): return False

            last_change = max(last_change, target_infile.stat().st_mtime)
            last_change = max(last_change, target_ansfile.stat().st_mtime)

            if not meta_path.is_file(): return False

            meta_yaml = yaml.safe_load(meta_path.open())
            return meta_path.stat().st_mtime >= last_change and meta_yaml == t.cache_data

        if up_to_date():
            check_deterministic()
            if config.args.action != 'generate':
                bar.logged = True  # Disable redundant 'up to date' message in run mode.
            bar.done(message='up to date')
            return

        # Generate .in
        if t.manual:
            # Clean the directory, but not the meta_ file.
            for f in cwd.iterdir():
                if f.name in ['meta_', 'meta_.yaml']: continue
                f.unlink()

            manual_data = problem.path / t.source
            assert manual_data.is_file()

            # For manual cases outside of the data/ directory, copy all related files.
            # Inside data/, only use the .in.

            # We make sure to not silently overwrite changes to files in data/
            # that are copied from generators/.
            for ext in config.KNOWN_DATA_EXTENSIONS:
                ext_file = manual_data.with_suffix(ext)
                if ext_file.is_file():
                    ensure_symlink(infile.with_suffix(ext), ext_file)
        else:
            result = t.generator.run(bar, cwd, t.name, t.seed, t.config.retries)
            if result.ok is not True:
                return

        testcase = run.Testcase(problem, infile, short_path=Path(t.path.parent / (t.name + '.in')))

        # Validate the manual or generated .in.
        if not testcase.validate_format('input_format', bar=bar, constraints=None):
            return

        # Generate .ans and .interaction if needed.
        # TODO: Disable this with a flag.
        if not problem.interactive:
            if t.config.solution and (not testcase.ans_path.is_file() or t.manual_inline):
                if testcase.ans_path.is_file():
                    testcase.ans_path.unlink()
                # Run the solution and validate the generated .ans.
                if t.config.solution.run(bar, cwd, t.name).ok is not True:
                    return

            if ansfile.is_file():
                if not testcase.validate_format('output_format', bar=bar):
                    return
            else:
                if not target_ansfile.is_file():
                    bar.warn(f'{ansfile.name} does not exist and was not generated.')
        else:
            if not testcase.ans_path.is_file(): testcase.ans_path.write_text('')
            # For interactive problems, run the interactive solution and generate a .interaction.
            if t.config.solution and testcase.sample:
                if not t.config.solution.run_interactive(problem, bar, cwd, t):
                    return

        # Generate visualization
        # TODO: Disable this with a flag.
        if t.config.visualizer:
            if t.config.visualizer.run(bar, cwd, t.name).ok is not True:
                return

        if t.path.parents[0] == Path('sample'):
            msg = '; supply -f --samples to override'
            forced = config.args.force and (config.args.action == 'all' or config.args.samples)
        else:
            msg = '; supply -f to override'
            forced = config.args.force

        skipped = False
        skipped_in = False
        for ext in config.KNOWN_DATA_EXTENSIONS:
            source = cwd / (t.name + ext)
            target = target_dir / (t.name + ext)

            if source.is_file():
                if target.is_file():
                    if source.read_bytes() == target.read_bytes():
                        # identical -> skip
                        continue
                    else:
                        # different -> overwrite
                        if not forced:
                            bar.warn(f'SKIPPED: {target.name}{Style.RESET_ALL}' + msg)
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

                # We always copy file contents. Manual cases are copied as well.
                if source.is_symlink():
                    shutil.copy(source, target, follow_symlinks=True)
                    #source = source.resolve().relative_to(problem.path.parent.resolve())
                    #ensure_symlink(target, source, relative=True)
                else:
                    shutil.move(source, target)
            else:
                if target.is_file():
                    # Target exists but source wasn't generated. Only remove the target with -f.
                    # When solution is disabled, this is fine for the .ans file.
                    if ext == '.ans' and t.config.solution is None:
                        continue

                    # remove old target
                    if not forced:
                        bar.warn(f'SKIPPED: {target.name}{Style.RESET_ALL}' + msg)
                        skipped = True
                        continue
                    else:
                        bar.log(f'REMOVED {target.name}')
                        target.unlink()
                else:
                    continue

        # Clean the directory.
        for f in cwd.glob('*'):
            if f.name == 'meta_': continue
            f.unlink()

        # Update metadata
        if not skipped:
            yaml.dump(t.cache_data, meta_path.open('w'))

        # If the .in was changed but not overwritten, check_deterministic will surely fail.
        if not skipped_in:
            check_deterministic()
        bar.done()

    def clean(t, problem, generator_config, bar):
        bar.start(str(t.path))

        path = Path('data') / t.path.with_suffix(t.path.suffix + '.in')

        # Skip cleaning manual cases that are their own source.
        if t.manual and t.source == path:
            bar.log(f'Keep manual case')
            bar.done()
            return

        infile = problem.path / path
        for ext in config.KNOWN_DATA_EXTENSIONS:
            ext_file = infile.with_suffix(ext)
            if ext_file.is_file():
                if ext == '.ans' and t.config.solution is None:
                    bar.log(f'Keep {ext_file.name} since solution is disabled.')
                    continue

                bar.log(f'Remove file {ext_file.name}')
                ext_file.unlink()

        bar.done()


class Directory(Rule):
    # Process yaml object for a directory.
    def __init__(self, problem, name: str = None, yaml: dict = None, parent=None):
        if name is None:
            self.name = ''
            self.config = Config(problem, Path('/'))
            self.path = Path('')
            self.numbered = False
            return

        assert is_directory(yaml)
        if name != '':
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(name):
                fatal(f'Directory "{name}" does not have a valid name.')

        super().__init__(problem, name, yaml, parent)

        if name == '':
            for key in yaml:
                if key in RESERVED_DIRECTORY_KEYS:
                    fatal(f'Directory must not contain reserved key {key}.')
                if key not in KNOWN_DIRECTORY_KEYS + KNOWN_ROOT_KEYS:
                    log(f'Unknown root level key: {key}')
        else:
            for key in yaml:
                if key in RESERVED_DIRECTORY_KEYS + KNOWN_ROOT_KEYS:
                    fatal(f'Directory must not contain reserved key {key}.')
                if key not in KNOWN_DIRECTORY_KEYS:
                    log(f'Unknown directory level key: {key} in {self.path}')

        if 'testdata.yaml' in yaml:
            self.testdata_yaml = yaml['testdata.yaml']
        else:
            self.testdata_yaml = None

        self.numbered = False
        # These field will be filled by parse().
        self.includes = []
        self.data = []

        # Sanity checks for possibly empty data.
        if 'data' not in yaml: return
        data = yaml['data']
        if data is None: return
        if data == '': return
        check_type('Data', data, [dict, list])

        if isinstance(data, dict):
            yaml['data'] = [data]
            data = yaml['data']
            if parent.numbered is True:
                fatal(
                    'Unnumbered data dictionaries may not appear inside numbered data lists at {self.path}.'
                )
        else:
            self.numbered = True
            if len(data) == 0: return

        for d in data:
            if isinstance(d, dict):
                if len(d) == 0:
                    fatal(f'Dictionaries in data should not be empty: {self.path}')

    # Map a function over all test cases directory tree.
    # dir_f by default reuses testcase_f
    def walk(self, testcase_f=None, dir_f=True, *, dir_last=False):
        if dir_f is True: dir_f = testcase_f

        if not dir_last and dir_f:
            dir_f(self)

        for d in self.data:
            if isinstance(d, Directory):
                d.walk(testcase_f, dir_f, dir_last=dir_last)
            elif isinstance(d, TestcaseRule):
                if testcase_f: testcase_f(d)
            else:
                assert False

        if dir_last and dir_f:
            dir_f(self)

    def generate(d, problem, generator_config, bar):
        # Generate the current directory:
        # - create the directory
        # - write testdata.yaml
        # - include linked testcases
        # - check for unknown manual cases
        bar.start(str(d.path))

        dir_path = problem.path / 'data' / d.path
        dir_path.mkdir(parents=True, exist_ok=True)

        files_created = []

        # Write the testdata.yaml, or remove it when the key is set but empty.
        testdata_yaml_path = dir_path / 'testdata.yaml'
        if d.testdata_yaml is not None:
            if d.testdata_yaml:
                yaml_text = yamllib.dump(d.testdata_yaml)
                if not testdata_yaml_path.is_file():
                    testdata_yaml_path.write_text(yaml_text)
                else:
                    if yaml_text != testdata_yaml_path.read_text():
                        if config.args.force:
                            bar.log(f'CHANGED testdata.yaml')
                            testdata_yaml_path.write_text(yaml_text)
                        else:
                            bar.warn(f'SKIPPED: testdata.yaml')

                files_created.append(testdata_yaml_path)
            if d.testdata_yaml == '' and testdata_yaml_path.is_file():
                testdata_yaml_path.unlink()

        # Symlink existing testcases.
        cases_to_link = []
        for include in d.includes:
            include = problem.path / 'data' / include
            if include.is_dir():
                cases_to_link += include.glob('*.in')
            elif include.with_suffix(include.suffix + '.in').is_file():
                cases_to_link.append(include.with_suffix(include.suffix + '.in'))
            else:
                assert False

        for case in cases_to_link:
            for ext in config.KNOWN_DATA_EXTENSIONS:
                ext_file = case.with_suffix(ext)
                if ext_file.is_file():
                    ensure_symlink(dir_path / ext_file.name, ext_file, relative=True)
                    files_created.append(dir_path / ext_file.name)

        # Add hardcoded manual cases not mentioned in generators.yaml, and warn for or delete other spurious files.
        # We sort files with .in preceding other extensions.
        files = list(dir_path.glob('*'))
        files.sort(key=lambda f: f.with_suffix('') if f.suffix == '.in' else f)

        # Only consider files matching --testcases, if given.
        files = list(filter(lambda p: process_testcase(problem, p), files))

        # First do a loop to find untracked manual .in files.
        for f in files:
            if f in files_created: continue
            base = f.with_suffix('')
            relpath = base.relative_to(problem.path / 'data')
            if relpath in generator_config.known_cases: continue
            if f.suffix != '.in': continue
            t = TestcaseRule(problem, base.name, None, d, tracked=False)
            assert t.manual_inline
            d.data.append(t)
            bar.add_item(t.path)

        for f in files:
            if f in files_created: continue
            base = f.with_suffix('')
            relpath = base.relative_to(problem.path / 'data')
            if relpath in generator_config.known_cases: continue
            if relpath in generator_config.known_directories: continue

            if f.suffix != '.in':
                if f.suffix in config.KNOWN_DATA_EXTENSIONS and f.with_suffix(
                        '.in') in files_created:
                    continue

                if f.with_suffix('.in').is_file():
                    continue

                if d.path == Path('.') and f.name == 'bad':
                    continue

                if f.name[0] != '.':
                    name = f.relative_to(problem.path / 'data')

                    ft = 'directory' if f.is_dir() else 'file'
                    if f.is_dir():
                        if config.args.add_manual:
                            bar.log(f'Adding directory {name} to generators.yaml')
                            generator_config.untracked_directory.add(relpath)
                        else:
                            bar.debug(
                                f'Track {ft} {name} using --add-manual/--move-manual or delete using clean -f.'
                            )
                    else:
                        bar.debug(f'Untracked {ft} {name}. Delete with clean -f.')
                continue

            generator_config.known_cases.add(relpath)
            if config.args.add_manual:
                bar.log(f'Adding {relpath.name}.in to generators.yaml')
                generator_config.untracked_inline_manual.add(relpath)
            else:
                bar.debug(
                    f'Track manual case {relpath}.in using --add-manual/--move-manual or delete using clean -f.'
                )

        bar.done()
        return True

    def clean(d, problem, generator_config, bar):
        # Clean the current directory:
        # - remove testdata.yaml
        # - remove linked testcases
        # - remove the directory if it's empty
        bar.start(str(d.path))

        dir_path = problem.path / 'data' / d.path

        # Remove the testdata.yaml when the key is present.
        testdata_yaml_path = dir_path / 'testdata.yaml'
        if d.testdata_yaml is not None and testdata_yaml_path.is_file():
            bar.log(f'Remove testdata.yaml')
            testdata_yaml_path.unlink()

        # Remove all symlinks that correspond to includes.
        for f in dir_path.glob('*'):
            if f.is_symlink():
                try:
                    target = Path(os.path.normpath(f.parent / os.readlink(f))).relative_to(
                        problem.path / 'data').with_suffix('')

                    if target in d.includes or target.parent in d.includes:
                        bar.log(f'Remove linked file {f.name}')
                        f.unlink()
                        continue
                except ValueError:
                    pass

            if f.name[0] == '.': continue

            if d.path == Path('.') and f.name == 'bad':
                continue

            # If --force/-f is passed, also clean unknown files.
            relpath = f.relative_to(problem.path / 'data')
            if relpath.with_suffix('') in generator_config.known_cases: continue
            if relpath.with_suffix('') in generator_config.known_directories: continue

            ft = 'directory' if f.is_dir() else 'file'

            if config.args.force:
                bar.log(f'Deleted untracked {ft}: {relpath}')
                f.unlink()
            else:
                bar.log(f'Found untracked {ft}. Delete with clean --force: {relpath}')

        # Try to remove the directory. Fails if it's not empty.
        try:
            dir_path.rmdir()
            bar.log(f'Remove directory {dir_path.name}')
        except:
            pass

        bar.done()


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
        ('generators', [], parse_generators),

        # Non-standard key. When set to True, run will be parallelized.
        ('parallel', True, lambda x: x is True),

        # Non-standard key. When set to True, all generated testcases will be .gitignored in data/.gitignore.
        ('gitignore_generated', False, lambda x: x is True),
    ]

    # Parse generators.yaml.
    def __init__(self, problem):
        self.problem = problem
        problem._rules_cache = dict()
        yaml_path = self.problem.path / 'generators/generators.yaml'
        self.ok = True
        if not yaml_path.is_file():
            log('Did not find generators/generators.yaml')
            self.ok = False
            return

        yaml = yamllib.load(yaml_path.read_text(), Loader=yamllib.SafeLoader)
        self.parse_yaml(yaml)

    def parse_yaml(self, yaml):
        check_type('Root yaml', yaml, [dict, None])
        if yaml is None: yaml = dict()
        yaml['type'] = 'directory'

        # Read root level configuration
        for key, default, func in GeneratorConfig.ROOT_KEYS:
            if yaml and key in yaml:
                setattr(self, key, func(yaml[key]))
            else:
                setattr(self, key, default)

        # A set of paths `secret/testgroup/testcase`, without the '.in'.
        self.known_cases = set()
        # A set of paths `secret/testgroup`.
        self.known_directories = set()
        self.untracked_inline_manual = set()
        self.untracked_directory = set()
        self.tracked_inline_manual = set()

        # Main recursive parsing function.
        def parse(name, yaml, parent):
            check_type('Testcase/directory', yaml, [None, str, dict], parent.path)
            if not is_testcase(yaml) and not is_directory(yaml):
                fatal(
                    f'Could not parse {parent.path/name} as a testcase or directory. Try setting the type: key.'
                )

            if is_testcase(yaml):
                if not config.COMPILED_FILE_NAME_REGEX.fullmatch(name + '.in'):
                    error(f'Testcase \'{parent.path}/{name}.in\' has an invalid name.')
                    return None

                # If a list of testcases was passed and this one is not in it, skip it.
                if not process_testcase(self.problem, self.problem.path / 'data' / parent.path / name): return None

                t = TestcaseRule(self.problem, name, yaml, parent)
                assert t.path not in self.known_cases
                self.known_cases.add(t.path)
                return t

            assert is_directory(yaml)

            d = Directory(self.problem, name, yaml, parent)
            assert d.path not in self.known_cases
            self.known_directories.add(d.path)

            if 'include' in yaml:
                assert isinstance(yaml['include'], list)
                for include in yaml['include']:
                    assert not include.startswith('/')
                    assert not Path(include).is_absolute()
                    # TODO: This, or self.known_directories.
                    assert Path(include) in self.known_cases
                    self.known_cases.add(d.path / Path(include).name)

                d.includes = [Path(include) for include in yaml['include']]

            # Parse child directories/testcases.
            if 'data' in yaml and yaml['data']:
                number_width = len(str(len(yaml['data'])))
                next_number = 1

                for dictionary in yaml['data']:
                    check_type('Elements of data', dictionary, dict, d.path)
                    if d.numbered:
                        number_prefix = f'{next_number:0{number_width}}'
                        next_number += 1
                    else:
                        number_prefix = ''

                    for key in dictionary:
                        check_type('Testcase/directory name', key, [str, None], d.path)

                    for child_name, child_yaml in sorted(dictionary.items()):
                        if number_prefix:
                            if child_name:
                                child_name = number_prefix + '-' + child_name
                            else:
                                assert child_name is None or child_name == ''
                                child_name = number_prefix
                        else:
                            if not child_name:
                                fatal(
                                    f'Unnumbered testcases must not have an empty key: {Path("data")/d.path/child_name}/\'\''
                                )
                        c = parse(child_name, child_yaml, d)
                        if c is not None:
                            d.data.append(c)

            return d

        self.root_dir = parse('', yaml, Directory(self.problem))

    # Return submission
    # This function will always raise a warning.
    # Which submission is used is implementation defined.
    def get_default_solution(self):
        # Use one of the accepted submissions.
        submissions = list(glob(self.problem.path, 'submissions/accepted/*'))
        if len(submissions) == 0:
            warn(f'No solution specified and no accepted submissions found.')
            return False

        # Note: we explicitly random shuffle the submission that's used to generate answers to
        # encourage setting it in generators.yaml.
        submission = random.choice(submissions)
        submission_short_path = submission.relative_to(self.problem.path / 'submissions')
        warn(f'No solution specified. Using randomly chosen {submission_short_path} instead.')
        return Path('/') / submission.relative_to(self.problem.path)

    def build(self, build_visualizers = True):
        generators_used = set()
        solutions_used = set()
        visualizers_used = set()

        default_solution = None

        # Collect all programs that need building.
        # Also, convert the default submission into an actual Invocation.
        def collect_programs(t):
            nonlocal default_solution
            if isinstance(t, TestcaseRule):
                if not t.manual:
                    generators_used.add(t.generator.program_path)
            if t.config.solution:
                if t.config.solution is True:
                    if default_solution is None:
                        default_solution_path = self.get_default_solution()
                        if default_solution_path:
                            default_solution = SolutionInvocation(self.problem,
                                                                  default_solution_path)
                        else:
                            default_solution = False
                    t.config.solution = default_solution
                if t.config.solution:
                    solutions_used.add(t.config.solution.program_path)
            if build_visualizers and t.config.visualizer:
                visualizers_used.add(t.config.visualizer.program_path)

        self.root_dir.walk(collect_programs, dir_f = None)

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
                            program_type(self.problem, path, skip_double_build_warning=True))
                    else:
                        programs.append(program_type(self.problem, path))

            bar = ProgressBar('Build ' + program_type.subdir, items=programs)

            # TODO: Build multiple programs in parallel.
            for p in programs:
                bar.start(p)
                p.build(bar)
                bar.done()

            bar.finalize(print_done=False)

        build_programs(program.Generator, generators_used)
        build_programs(run.Submission, solutions_used)
        build_programs(program.Visualizer, visualizers_used)

        def unset_build_failures(t):
            if t.config.solution and t.config.solution.program is None:
                t.config.solution = None
            if not build_visualizers or (t.config.visualizer and t.config.visualizer.program is None):
                t.config.visualizer = None

        self.root_dir.walk(unset_build_failures, dir_f = None)

        self.problem.validators('input_format')
        self.problem.validators('output_format')

    def run(self):
        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))

        self.problem.reset_testcase_hashes()

        bar = ProgressBar('Generate', items=item_names)

        parallel = True
        if self.parallel and config.args.jobs > 1 and self.problem.interactive:
            parallel = False
            log('Disabling parallelization for interactive problem.')

        if not self.parallel or config.args.jobs <= 1:
            parallel = False
            log('Disabling parallelization.')

        if not parallel:
            self.root_dir.walk(
                lambda t: t.generate(self.problem, self, bar),
                lambda d: d.generate(self.problem, self, bar),
            )
        else:
            # Parallelize generating test cases.
            # All testcases are generated in separate threads. Directories are still handled by the
            # main thread. We only start processing a directory after all preceding test cases have
            # completed to avoid problems with including cases.
            q = queue.Queue()
            error = None

            # TODO: Make this a generators.yaml option?
            num_worker_threads = config.args.jobs

            def clear_queue(e=True):
                nonlocal num_worker_threads, error
                if error is not None: return
                error = e
                try:
                    while True:
                        q.get(block=False)
                        q.task_done()
                except queue.Empty:
                    pass
                for _ in range(num_worker_threads):
                    q.put(None)
                    q.task_done()

            def worker():
                try:
                    while True:
                        testcase = q.get()
                        if testcase is None: break
                        testcase.generate(self.problem, self, bar)
                        q.task_done()
                except Exception as e:
                    q.task_done()
                    clear_queue(e)

            threads = []
            for _ in range(num_worker_threads):
                t = threading.Thread(target=worker)
                t.start()
                threads.append(t)

            def interrupt_handler(sig, frame):
                clear_queue()
                fatal('Running interrupted')

            signal.signal(signal.SIGINT, interrupt_handler)

            def maybe_join():
                if error is not None:
                    raise error
                q.join()

            def generate_dir(d):
                maybe_join()
                d.generate(self.problem, self, bar)

            self.root_dir.walk(
                q.put,
                generate_dir,
            )

            maybe_join()

            for _ in range(num_worker_threads):
                q.put(None)

            for t in threads:
                t.join()

            if error is not None:
                raise error

        bar.finalize()

        self.update_gitignore_file()
        if config.args.add_manual:
            self.add_untracked_manual_to_generators_yaml()
        if config.args.move_manual:
            self.move_inline_manual_to_directory()

    def update_gitignore_file(self):
        gitignorefile = self.problem.path / 'data/.gitignore'
        if self.gitignore_generated:
            # Collect all generated testcases and all non inline manual testcases and gitignore them in the data/ directory.
            # When only generating a subset of testcases, we also keep existing entries not matching the filter.
            cases_to_ignore = []

            def maybe_ignore_testcase(t):
                if not t.manual_inline:
                    cases_to_ignore.append(t.path)

            self.root_dir.walk(maybe_ignore_testcase, None)

            if config.args.testcases and gitignorefile.is_file():
                for line in gitignorefile.read_text().splitlines():
                    if line[0] == '#' or line == '.gitignore': continue
                    assert line.endswith('.*')
                    line = Path(line).with_suffix('')
                    path = self.problem.path / 'data' / line
                    if not process_testcase(self.problem, path):
                        # Remove the .*.
                        cases_to_ignore.append(line)
            cases_to_ignore.sort()

            def write_gitignore_file():
                if len(cases_to_ignore) == 0:
                    return

                if gitignorefile.is_file():
                    text = gitignorefile.read_text()
                    if not text.startswith('# GENERATED BY BAPCtools' ):
                        warn('Not overwriting existing data/.gitignore file.')
                        return
                else:
                    text = ''

                content = '# GENERATED BY BAPCtools\n# Do not modify.\n.gitignore\n'
                for path in cases_to_ignore:
                    content += str(path) + '.*\n'
                if content != text:
                    gitignorefile.write_text(content)
                    if config.args.verbose:
                        log('Updated data/.gitignore.')

            write_gitignore_file()
        else:
            if gitignorefile.is_file():
                text = gitignorefile.read_text()
                if text.startswith('# GENERATED BY BAPCtools'):
                    gitignorefile.unlink()
                    log('Deleted data/.gitignore.')

    def add_untracked_manual_to_generators_yaml(self):
        try:
            import ruamel.yaml
        except:
            error(
                'generate --add-manual needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.'
            )
            return

        if len(self.untracked_inline_manual) == 0 and len(self.untracked_directory) == 0:
            if not config.args.move_manual:
                log('No untracked manual cases found.')
            return

        generators_yaml = self.problem.path / 'generators/generators.yaml'

        # Round-trip parsing.
        yaml = ruamel.yaml.YAML(typ='rt')
        yaml.default_flow_style = False
        yaml.indent(mapping=2, sequence=4, offset=2)
        data = yaml.load(generators_yaml)

        if data is None:
            data = ruamel.yaml.comments.CommentedMap()

        # Add missing directories.
        for path in sorted(self.untracked_directory):
            d = data
            for directory in path.parent.parts:
                d = d['data'][directory]

            if 'data' not in d:
                d['data'] = ruamel.yaml.comments.CommentedMap()
            if d['data'] is None:
                d['data'] = ruamel.yaml.comments.CommentedMap()

            if isinstance(d['data'], ruamel.yaml.comments.CommentedMap):
                d['data'][path.name] = {'type': 'directory', 'data': None}
            elif isinstance(d['data'], ruamel.yaml.comments.CommentedSeq):
                error(f'Manual case cannot be added to directory {path.parent} which is numbered.')
            else:
                assert False

        # Add missing testcases.
        for path in sorted(self.untracked_inline_manual):
            d = data
            for directory in path.parent.parts:
                d = d['data'][directory]

            if 'data' not in d or d['data'] is None:
                d['data'] = ruamel.yaml.comments.CommentedMap()
            if isinstance(d['data'], ruamel.yaml.comments.CommentedMap):
                d['data'][path.name] = None
            elif isinstance(d['data'], ruamel.yaml.comments.CommentedSeq):
                error(f'Manual case cannot be added to directory {path.parent} which is numbered.')
            else:
                assert False

            # Add path to tracked cases, so they can be moved afterwards if needed.
            self.tracked_inline_manual.add(path)

        # Overwrite generators.yaml.
        yaml.dump(data, generators_yaml)
        log('Updated generators.yaml')

    def move_inline_manual_to_directory(self):
        try:
            import ruamel.yaml
        except:
            error(
                'generate --move-manual needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.'
            )
            return

        if len(self.tracked_inline_manual) == 0:
            log('No inline manual cases found.')
            return

        generators_yaml = self.problem.path / 'generators/generators.yaml'

        # Round-trip parsing.
        yaml = ruamel.yaml.YAML(typ='rt')
        yaml.default_flow_style = False
        yaml.indent(mapping=2, sequence=4, offset=2)
        data = yaml.load(generators_yaml)

        assert data

        config.args.move_manual.mkdir(exist_ok=True)

        # Add missing testcases.
        for path in sorted(self.tracked_inline_manual):
            d = data
            for directory in path.parent.parts:
                d = d['data'][directory]

            # Move all test data.
            # Make sure the testcase doesn't already exist in the target directory.
            in_target = (config.args.move_manual / (path.name + '.in'))
            if in_target.is_file():
                warn(
                    f'Target file {in_target.relative_to(self.problem.path.resolve())} already exists. Skipping testcase {path}.'
                )
                continue

            assert path.name in d['data']

            d['data'][path.name] = str(
                in_target.relative_to(self.problem.path.resolve() / 'generators'))

            for ext in config.KNOWN_DATA_EXTENSIONS:
                source = (self.problem.path / 'data') / (path.parent / (path.name + ext))
                target = config.args.move_manual / (path.name + ext)
                if source.is_file():
                    shutil.copy(source, target)

        # Overwrite generators.yaml.
        yaml.dump(data, generators_yaml)
        log('Updated generators.yaml')

    def clean(self):
        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))

        bar = ProgressBar('Clean', items=item_names)

        self.root_dir.walk(lambda x: x.clean(self.problem, self, bar), dir_last=True)
        bar.finalize()


def generate(problem):
    config = GeneratorConfig(problem)
    if config.ok:
        config.build()
        config.run()
    return True


def clean(problem):
    config = GeneratorConfig(problem)
    if config.ok:
        config.clean()
    return True


def generated_testcases(problem):
    config = GeneratorConfig(problem)
    if config.ok:
        return config.known_cases
    return set()
