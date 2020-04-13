import hashlib
import random
import re
import shlex
import shutil
import yaml as yamllib

from util import *
from pathlib import Path

import config
import build
import validate
import run


def is_testcase(yaml):
    return yaml == '' or isinstance(yaml, str) or (isinstance(yaml, dict) and 'input' in yaml)


def is_directory(yaml):
    return isinstance(yaml, dict) and 'type' in yaml and yaml['type'] == 'directory'


def resolve_path(path, *, allow_absolute):
    assert isinstance(path, str)
    if not allow_absolute:
        assert not path.startswith('/')
        assert not Path(path).is_absolute()

    # Make all paths relative to the problem root.
    if path.startswith('/'):
        return Path(path[1:])
    else:
        return Path('generators') / path


# Return (submission, msg)
# This function will always raise a warning.
# Which submission is used is implementation defined. We prefer c++ because it tends to be faster.
def get_default_solution(problem):
    # Use one of the accepted submissions.
    submissions = list(glob(problem.path, 'submissions/accepted/*'))
    if len(submissions) == 0:
        return None

    submissions.sort()

    # Look for a (hopefully fast) c++ solution if available.
    submission = submissions[0]
    for s in submissions:
        if s.suffix == '.cpp':
            submission = s
            break

    warn(f'No solution specified. Falling back to {submission}.')
    return submission


# Parses a string into command to execute and arguments to give on the command line.
class Program:
    SEED_REGEX = re.compile('\{seed(:[0-9]+)?\}')
    NAME_REGEX = re.compile('\{name\}')

    def __init__(self, string, *, allow_absolute):
        commands = shlex.split(str(string))
        command = commands[0]
        self.args = commands[1:]
        # Will be set after programs have been built.
        self.exec = None

        self.command = resolve_path(command, allow_absolute=allow_absolute)

        # Make sure that {seed} occurs at most once.
        seed_cnt = 0
        for arg in self.args:
            seed_cnt += len(self.SEED_REGEX.findall(arg))

        assert seed_cnt <= 1

    def substitute_args(self, *, name=None, seed=None):
        def sub(arg):
            if name: arg = self.NAME_REGEX.sub(str(name), arg)
            if seed: arg = self.SEED_REGEX.sub(str(seed), arg)

        return [sub(arg) for arg in self.args]


class Generator(Program):
    def __init__(self, string):
        super().__init__(string, allow_absolute=False)

    # Run this program in the given working directory for the given name and seed.
    # May write files in |cwd| and stdout is piped to {name}.in if it's not written already.
    # Returns True on success, False on failure.
    def run(self, bar, cwd, name, seed, retries=1):
        in_path = cwd / (name + '.in')
        stdout_path = cwd / (name + '.in_')

        timeout = get_timeout()

        # Try running the command |retries| times.
        ok = False
        for retry in range(retries):
            # Clean the directory.
            for f in cwd.iterdir():
                f.unlink()

            assert self.exec is not None

            command = self.exec + self.substitute_args(name=name, seed=seed+retry)

            stdout_file = stdout_path.open('w')
            try_ok, err, out = exec_command(command, stdout=stdout_file, timeout=timeout, cwd=cwd)
            stdout_file.close()

            if try_ok == -9:
                # Timeout -> stop retrying and fail.
                bar.error(f'TIMEOUT after {timeout}s')
                return False

            if try_ok is not True:
                # Other error -> try again.
                continue

            if in_path.is_file():
                if stdout_path.is_file():
                    bar.warn(f'Wrote both {name}.in and stdout. Ignoring stdout.')
            else:
                if not stdout_path.is_file():
                    bar.error(f'Did not write {name}.in and stdout is empty!')
                    return False

            if stdout_path.is_file():
                stdout_path.rename(in_path)
            ok = True

        if not ok:
            if retries > 1:
                bar.error(f'Failed {retry+1} times', err)
            else:
                bar.error(f'Failed', err)
            return False
        else:
            return True


class Solution(Program):
    def __init__(self, string):
        super().__init__(string, allow_absolute=True)

    # Run the submission, reading {name}.in from stdin and piping stdout to {name}.ans.
    # If the .ans already exists, nothing is done.
    def run(self, bar, cwd, name):
        assert self.exec is not None
        timeout = get_timeout()

        in_path = cwd / (name + '.in')
        ans_path = cwd / (name + '.ans')

        if ans_path.is_file(): return True

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        ok, duration, err, out = run.run_testcase(self.exec + self.args, in_path, ans_path, timeout)
        if duration > timeout:
            bar.error('TIMEOUT')
            return False
        if ok is not True:
            bar.error('FAILED')
            return False

        return True

    def run_interactor(self, bar, cwd, name, output_validators):
        assert self.exec is not None
        timeout = get_timeout()

        in_path = cwd / (name + '.in')
        interaction_path = cwd / (name + '.interaction')
        if interaction_path.is_file(): return True

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        verdict, duration, err, out = run.process_interactive_testcase(self.exec + self.args,
                                                                       in_path,
                                                                       settings,
                                                                       output_validators,
                                                                       validator_error=None,
                                                                       team_error=None,
                                                                       interaction=interaction_path)
        if verdict != 'ACCEPTED':
            if duration > timeout:
                bar.error('TIMEOUT')
                nfail += 1
            else:
                bar.error('FAILED')
                nfail += 1
            return False

        return True



class Visualizer(Program):
    def __init__(self, string):
        super().__init__(string, allow_absolute=True)

    # Run the visualizer, taking {name} as a command line argument.
    # Stdin and stdout are not used.
    def run(self, bar, cwd, name):
        assert self.exec is not None

        timeout = get_timeout()
        command = self.exec + self.substitute_args(name=name)

        try_ok, err, out = exec_command(command, timeout=timeout, cwd=cwd)

        if try_ok == -9:
            bar.error(f'TIMEOUT after {timeout}s')
            return False
        if try_ok is not True:
            bar.error('FAILED')
            return False

        return True


# Holds all inheritable configuration options. Currently:
# - config.solution
# - config.visualizer
# - config.random_salt
class Config:
    INHERITABLE_KEYS = [
        # True: use an AC submission by default when the solution: key is not present.
        ('solution', True, lambda x: Solution(x) if x else None),
        ('visualizer', None, lambda x: Visualizer(x) if x else None),
        ('random_salt', '', None),

        # Non-portable keys only used by BAPCtools:
        # The number of retries to run a generator when it fails, each time incrementing the {seed}
        # by 1.
        ('retries', 1, int),
    ]

    def __init__(self, yaml=None, parent_config=None):
        assert not yaml or isinstance(yaml, dict)

        for key, default, func in self.INHERITABLE_KEYS:
            if func is None: func = lambda x: x
            if yaml and key in yaml:
                setattr(self, key, func(yaml[key]))
            elif parent_config is not None:
                setattr(self, key, vars(parent_config)[key])
            else:
                setattr(self, key, default)


class Base:
    def __init__(self, name, yaml, parent):
        assert parent is not None

        if isinstance(yaml, dict):
            self.config = Config(yaml, parent.config)
        else:
            self.config = parent.config

        # Directory key of the current directory/testcase.
        self.name = name
        # Path of the current directory/testcase relative to data/.
        self.path: Path = parent.path / self.name


class Testcase(Base):
    def __init__(self, name: str, yaml, parent):
        assert is_testcase(yaml)
        assert config.COMPILED_FILE_NAME_REGEX.fullmatch(name + '.in')

        self.manual = False

        if yaml == '':
            self.manual = True
            yaml = {'input': Path('data') / parent.path / (name + '.in')}
        elif isinstance(yaml, str) and yaml.endswith('.in'):
            self.manual = True
            yaml = {'input': resolve_path(yaml, allow_absolute=False)}
        elif isinstance(yaml, str):
            yaml = {'input': yaml}
        elif isinstance(yaml, dict):
            assert 'input' in yaml
            assert yaml['input'] is None or isinstance(yaml['input'], str)
        else:
            assert False

        super().__init__(name, yaml, parent)

        if self.manual:
            self.source = yaml['input']
        else:
            # TODO: Should the seed depend on white space? For now it does.
            seed_value = self.config.random_salt + yaml['input']
            self.seed = int(hashlib.sha512(seed_value.encode('utf-8')).hexdigest(), 16) % (2**31)
            self.program = Generator(yaml['input'])


class Directory(Base):
    # Process yaml object for a directory.
    def __init__(self, name: str = None, yaml: dict = None, parent=None):
        if name is None:
            self.name = ''
            self.config = Config()
            self.path = Path('')
            self.numbered = False
            return

        assert is_directory(yaml)
        if name != '':
            assert config.COMPILED_FILE_NAME_REGEX.fullmatch(name)

        super().__init__(name, yaml, parent)

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
        assert isinstance(data, dict) or isinstance(data, list)
        if len(data) == 0: return

        if isinstance(data, dict):
            yaml['data'] = [data]
            assert parent.numbered is False

        if isinstance(data, list):
            self.numbered = True

    # Map a function over all test cases directory tree.
    def walk(self, testcase_f=None, dir_f=None, *, dir_first=True):
        for d in self.data:
            if isinstance(d, Directory):
                if dir_first and dir_f:
                    dir_f(d)
                d.walk(testcase_f, dir_f, dir_first=dir_first)
                if not dir_first and dir_f:
                    dir_f(d)
            elif isinstance(d, Testcase):
                if testcase_f: testcase_f(d)
            else:
                assert False


class GeneratorConfig:
    def parse_generators(generators_yaml):
        generators = {}
        for gen in generators_yaml:
            assert not gen.startswith('/')
            assert not Path(gen).is_absolute()
            assert config.COMPILED_FILE_NAME_REGEX.fullmatch(gen + '.x')

            deps = generators_yaml[gen]

            generators[Path('generators') / gen] = [Path('generators') / d for d in deps]
        return generators

    ROOT_KEYS = [
        ('generators', [], parse_generators),
    ]

    # Parse generators.yaml.
    def __init__(self, problem):
        self.problem = problem
        yaml_path = self.problem.path / 'generators/generators.yaml'
        if not yaml_path.is_file(): exit(1)

        yaml = yamllib.load(yaml_path.read_text(), Loader=yamllib.BaseLoader)

        assert isinstance(yaml, dict)
        yaml['type'] = 'directory'

        # Read root level configuration
        for key, default, func in self.ROOT_KEYS:
            if yaml and key in yaml:
                # TODO: Parse generators array to something more usable.
                setattr(self, key, func(yaml[key]))
            else:
                setattr(self, key, default)

        next_number = 1
        # A map from directory paths `secret/testgroup` to Directory objects, used to resolve testcase
        # inclusion.
        self.known_cases = set()

        # Main recursive parsing function.
        def parse(name, yaml, parent):
            nonlocal next_number

            assert is_testcase(yaml) or is_directory(yaml)

            if is_testcase(yaml):
                t = Testcase(name, yaml, parent)
                assert t.path not in self.known_cases
                self.known_cases.add(t.path)
                return t

            assert is_directory(yaml)

            d = Directory(name, yaml, parent)
            assert d.path not in self.known_cases
            self.known_cases.add(d.path)

            if 'include' in yaml:
                assert isinstance(yaml['include'], list)
                for include in yaml['include']:
                    assert not include.startswith('/')
                    assert not Path(include).is_absolute()
                    assert Path(include) in self.known_cases

                d.includes = [Path(include) for include in yaml['include']]

            if 'data' not in yaml: return d

            for dictionary in yaml['data']:
                if d.numbered:
                    number_prefix = str(next_number) + '-'
                    next_number += 1
                else:
                    number_prefix = ''

                for child_name, child_yaml in sorted(dictionary.items()):
                    if isinstance(child_name, int): child_name = str(child_name)
                    child_name = number_prefix + child_name
                    d.data.append(parse(child_name, child_yaml, d))

            return d

        self.root_dir = parse('', yaml, Directory())

    # Return (submission, msg)
    # This function will always raise a warning.
    # Which submission is used is implementation defined. We prefer c++ because it tends to be faster.
    def get_default_solution(self):
        # By default don't do anything for interactive problems.
        if self.problem.config.validation == 'custom interactive':
            return None

        # Use one of the accepted submissions.
        submissions = list(glob(problem.path, 'submissions/accepted/*'))
        if len(submissions) == 0:
            return None

        # Note: we explicitly random shuffle the submission that's used to generate answers to
        # encourage setting it in generators.yaml.
        random.shuffle(submissions)

        # Look for a (hopefully fast) c++ solution if available.
        submission = submissions[0]
        for s in submissions:
            if s.suffix == '.cpp':
                submission = s
                break

        warn(f'No solution specified. Using randomly chosen {submission} instead.')
        return submission

    # TODO: Determine which test cases need updating, and only build required programs.

    def build(self):
        generators_used = set()
        solutions_used = set()
        visualizers_used = set()

        default_solution = None

        # Collect all programs that need building.
        # Also, convert the default submission into an actual Program.
        def collect_programs(t):
            nonlocal default_solution
            if not t.manual:
                generators_used.add(t.program.command)
            if t.config.solution:
                if t.config.solution is True:
                    if default_solution is None:
                        default_solution = Solution(get_default_solution(self.problem))
                    t.config.solution = default_solution
                solutions_used.add(t.config.solution.command)
            if t.config.visualizer:
                visualizers_used.add(t.config.visualizer.command)

        self.root_dir.walk(collect_programs)

        def build_programs(name, programs, *, allow_generators_dict=False):
            bar = ProgressBar('Build ' + name, items=[prog.name for prog in programs])
            commands = {}
            for prog in programs:
                bar.start(prog.name)

                path = self.problem.path / prog
                deps = None

                if allow_generators_dict and prog in self.generators:
                    deps = [Path(self.problem.path) / d for d in self.generators[prog]]

                run_command, message = build.build(path, deps)

                if run_command is not None:
                    commands[prog] = run_command
                if message:
                    bar.log(message)
                bar.done()

            return commands

        self.generator_commands = build_programs('generators',
                                                 generators_used,
                                                 allow_generators_dict=True)
        self.solution_commands = build_programs('solutions', solutions_used)
        self.visualizer_commands = build_programs('visualizers', visualizers_used)

        def set_exec(t):
            if not t.manual:
                t.program.exec = self.generator_commands[t.program.command]
            if t.config.solution:
                t.config.solution.exec = self.solution_commands[t.config.solution.command]
            if t.config.visualizer:
                t.config.visualizer.exec = self.visualizer_commands[t.config.visualizer.command]

        self.root_dir.walk(set_exec)

        self.input_validators = validate.get_validators(self.problem.path, 'input')
        self.output_validators = validate.get_validators(self.problem.path, 'output')


    def run(self):
        item_names = []
        self.root_dir.walk(lambda t: item_names.append(t.path),
                           lambda d: item_names.append(d.path))

        bar = ProgressBar('Generate', items=item_names)

        success = True

        # TODO: Move to Directory class.
        # Generate the current directory:
        # - create the directory
        # - write testdata.yaml
        # - include linked testcases
        # - check for unknown manual cases
        def generate_dir(d):
            bar.start(str(d.path))

            dir_path = self.problem.path / 'data' / d.path
            dir_path.mkdir(parents=True, exist_ok=True)

            # Write the testdata.yaml, or remove it when the key is set but empty.
            testdata_yaml_path = dir_path / 'testdata.yaml'
            if d.testdata_yaml is not None:
                if d.testdata_yaml:
                    # TODO: Only write on file changed?
                    yamllib.dump(d.testdata_yaml, testdata_yaml_path.open('w'))
                if d.testdata_yaml == '' and testdata_yaml_path.is_file():
                    testdata_yaml_path.unlink()

            # Symlink existing testcases.
            for include in d.includes:
                include = self.problem.path / 'data' / include
                if include.is_dir():
                    # include all cases in the directory
                    for case in include.glob('*.in'):
                        for ext in config.KNOWN_DATA_EXTENSIONS:
                            ext_file = case.with_suffix(ext)
                            if ext_file.is_file():
                                ensure_symlink(dir_path / ext_file.name, ext_file, relative=True)
                elif include.with_suffix(include.suffix+'.in').is_file():
                    # include the testcase
                    for ext in config.KNOWN_DATA_EXTENSIONS:
                        ext_file = include.with_suffix(ext)
                        if ext_file.is_file():
                            ensure_symlink(dir_path / ext_file.name, ext_file, relative=True)
                else:
                    assert False

            # TODO: Check for unlisted files.

            bar.done()

        # TODO: Move to Testcase class.
        # TODO: Support interactive problems again.
        def generate_testcase(t):

            bar.start(str(t.path))

            # E.g. bapctmp/problem/data/secret/1.in
            cwd = config.tmpdir / self.problem.id / 'data' / t.path
            cwd.mkdir(parents=True, exist_ok=True)
            infile = cwd / (t.name+'.in')
            ansfile = cwd / (t.name+'.ans')

            nonlocal success

            # Generate .in
            if t.manual:
                manual_data = self.problem.path / t.source
                if not manual_data.is_file():
                    bar.error(f'Manual source {t.source} not found.')
                    return

                for ext in config.KNOWN_DATA_EXTENSIONS:
                    ext_file = manual_data.with_suffix(ext)
                    if ext_file.is_file():
                        ensure_symlink(infile.with_suffix(ext), ext_file)
            else:
                success &= t.program.run(bar, cwd, t.name, t.seed, t.config.retries)

            if not success: return
        
            # Validate the manual or generated .in.
            if not validate.validate_testcase(self.problem, infile, self.input_validators, 'input', bar=bar):
                return
            
            # Generate .ans and/or .interaction for interactive problems.
            # TODO: Disable this with a flag.
            if t.config.solution:

                if self.problem.settings.validation != 'custom interactive':
                    success &= t.config.solution.run(bar, cwd, t.name)
                    if not validate.validate_testcase(self.problem, ansfile, self.output_validators, 'input', bar=bar):
                        return
                else:
                    success &= t.config.solution.run_interactive(bar, cwd, t.name, self.output_validators)
                if not success: return

            # Generate visualization
            # TODO: Disable this with a flag.
            if t.config.visualizer:
                success &= t.config.visualizer.run(bar, cwd, t.name)

                if not success: return


            # TODO: Copy files to data.
            # TODO: Delete tmpfs files.
            # TODO: Add dry-run flag.

            
            target_dir = self.problem.path / 'data' / t.path.parent
            if t.path.parents[0] == Path('sample'):
                msg = '; supply -f --samples to override'
                forced = self.problem.settings.force and self.problem.settings.samples
            else:
                msg = '; supply -f to override'
                forced = self.problem.settings.force

            for ext in config.KNOWN_DATA_EXTENSIONS:
                source = cwd / (t.name + ext)
                target = target_dir / (t.name+ext)

                if source.is_file():
                    if target.is_file():
                        if source.read_text() == target.read_text():
                            # identical -> skip
                            continue
                        else:
                            # different -> overwrite
                            if not forced:
                                bar.warn(f'SKIPPED: {target.name}{cc.reset}' + msg)
                                continue
                            bar.log(f'CHANGED {target.name}')
                    else:
                        # new file -> move it
                        bar.log(f'NEW {target.name}')

                    # Symlinks have to be made relative to the problem root again.
                    if source.is_symlink():
                        source = source.resolve().relative_to(self.problem.path.parent.resolve())
                        ensure_symlink(target, source, relative=True)
                    else:
                        source.rename(target)
                else:
                    if target.is_file():
                        # remove old target
                        if not forced:
                            bar.warn(f'SKIPPED: {target.name}{cc.reset}' + msg)
                            continue
                        else:
                            bar.warn(f'REMOVED {target.name}')
                            target.unlink()
                    else:
                        continue

            for f in cwd.glob('*'):
                f.unlink()

            bar.done()

        # TODO: Walk in parallel.
        self.root_dir.walk(generate_testcase, generate_dir)
        bar.finalize()

    def clean(self):
        item_names = []
        self.root_dir.walk(lambda t: item_names.append(t.path),
                           lambda d: item_names.append(d.path))

        bar = ProgressBar('Clean', items=item_names)

        # TODO: Move to Directory class.
        # Clean the current directory:
        # - remove testdata.yaml
        # - remove linked testcases
        # - remove the directory if it's empty
        def clean_dir(d):
            bar.start(str(d.path))

            dir_path = self.problem.path / 'data' / d.path

            # Remove the testdata.yaml when the key is present.
            testdata_yaml_path = dir_path / 'testdata.yaml'
            if d.testdata_yaml is not None and testdata_yaml_path.is_file():
                bar.log(f'Remove testdata.yaml')
                testdata_yaml_path.unlink()

            # Remove all symlinks that correspond to includes.
            for f in dir_path.glob('*'):
                if f.is_symlink():
                    relative_link_target = f.resolve().relative_to(self.problem.path.resolve()/'data')
                    if relative_link_target in self.known_cases:
                        bar.log(f'Remove linked file {f.name}')
                        f.unlink()

            # Try to remove the directory. Fails if it's not empty.
            try:
                dir_path.rmdir()
                bar.log(f'Remove directory {dir_path.name}')
            except:
                pass

            bar.done()

        # TODO: Move to Testcase class.
        # Delete all files associated with a test case.
        def clean_testcase(t):
            bar.start(str(t.path))

            path = Path('data') / t.path.with_suffix(t.path.suffix+'.in')

            # Skip cleaning manual cases that are their own source.
            if t.manual and t.source == path:
                bar.log(f'Keep manual case')
                bar.done()
                return

            infile = self.problem.path / path
            for ext in config.KNOWN_DATA_EXTENSIONS:
                ext_file = infile.with_suffix(ext)
                if ext_file.is_file():
                    bar.log(f'Remove file {ext_file.name}')
                    ext_file.unlink()

            bar.done()

        self.root_dir.walk(clean_testcase, clean_dir, dir_first=False)
        bar.finalize()


def test_generate(problem):
    config = GeneratorConfig(problem)
    config.build()
    config.run()
    exit(0)

def clean(problem):
    config = GeneratorConfig(problem)
    config.clean()
    exit(0)
