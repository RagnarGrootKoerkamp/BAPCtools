import hashlib
import random
import re
import shlex
import shutil
import yaml as yamllib
import queue
import threading
import distutils.util

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


# A Program is a command line (generator name + arguments) to execute.
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
            return arg

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

            command = self.exec + self.substitute_args(name=name, seed=seed + retry)

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
                if stdout_path.read_text():
                    bar.warn(f'Generator wrote to both {name}.in and stdout. Ignoring stdout.')
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
        ok, duration, err, out = run.run_testcase(self.exec + self.args, in_path, ans_path,
                                                  timeout)
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
        verdict, duration, err, out = run.process_interactive_testcase(
            self.exec + self.args,
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

    def generate(t, problem, input_validators, output_validators, bar):
        bar = bar.start(str(t.path))

        # E.g. bapctmp/problem/data/secret/1.in
        cwd = config.tmpdir / problem.id / 'data' / t.path
        cwd.mkdir(parents=True, exist_ok=True)
        infile = cwd / (t.name + '.in')
        ansfile = cwd / (t.name + '.ans')

        # Generate .in
        if t.manual:
            manual_data = problem.path / t.source
            if not manual_data.is_file():
                bar.error(f'Manual source {t.source} not found.')
                return

            for ext in config.KNOWN_DATA_EXTENSIONS:
                ext_file = manual_data.with_suffix(ext)
                if ext_file.is_file():
                    ensure_symlink(infile.with_suffix(ext), ext_file)
        else:
            if not t.program.run(bar, cwd, t.name, t.seed, t.config.retries):
                return

        # Validate the manual or generated .in.
        if not validate.validate_testcase(problem, infile, input_validators, 'input', bar=bar):
            return

        # Generate .ans and/or .interaction for interactive problems.
        # TODO: Disable this with a flag.
        if t.config.solution:
            if problem.settings.validation != 'custom interactive':
                if not t.config.solution.run(bar, cwd, t.name):
                    return
                if not validate.validate_testcase(
                        problem, ansfile, output_validators, 'input', bar=bar):
                    return
            else:
                if not t.config.solution.run_interactive(bar, cwd, t.name, output_validators):
                    return

        # Generate visualization
        # TODO: Disable this with a flag.
        if t.config.visualizer:
            if not t.config.visualizer.run(bar, cwd, t.name):
                return

        target_dir = problem.path / 'data' / t.path.parent
        if t.path.parents[0] == Path('sample'):
            msg = '; supply -f --samples to override'
            forced = problem.settings.force and problem.settings.samples
        else:
            msg = '; supply -f to override'
            forced = problem.settings.force

        for ext in config.KNOWN_DATA_EXTENSIONS:
            source = cwd / (t.name + ext)
            target = target_dir / (t.name + ext)

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
                    source = source.resolve().relative_to(problem.path.parent.resolve())
                    ensure_symlink(target, source, relative=True)
                else:
                    shutil.move(source, target)
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

    def clean(t, problem, bar):
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
                bar.log(f'Remove file {ext_file.name}')
                ext_file.unlink()

        bar.done()


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
    # dir_f by default reuses testcase_f
    def walk(self, testcase_f=None, dir_f=True, *, dir_last=False):
        if dir_f is True: dir_f = testcase_f
        for d in self.data:
            if isinstance(d, Directory):
                if not dir_last and dir_f:
                    dir_f(d)
                d.walk(testcase_f, dir_f, dir_last=dir_last)
                if dir_last and dir_f:
                    dir_f(d)
            elif isinstance(d, Testcase):
                if testcase_f: testcase_f(d)
            else:
                assert False

    def generate(d, problem, known_cases, bar):
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
                if not testdata_yaml_path.is_file() or yaml_text != testdata_yaml_path.read_text():
                    testdata_yaml_path.write_text(yaml_text)
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

        # Add hardcoded manual cases not mentioned in generators.yaml, and warn for other spurious files.
        for f in dir_path.glob('*'):
            if f in files_created: continue
            base = f.with_suffix('')
            relpath = base.relative_to(problem.path / 'data')
            if relpath in known_cases: continue

            if f.suffix != '.in':
                if f.suffix in config.KNOWN_DATA_EXTENSIONS and f.with_suffix('.in') in files_created: continue
                bar.warn(f'Found unlisted file {f}')
                continue

            known_cases.add(relpath)
            bar.warn(f'Found unlisted manual case: {relpath}')
            t = Testcase(base.name, '', d)
            d.data.append(t)
            bar.add_item(t.path)

        bar.done()
        return True

    def clean(d, problem, bar):
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
                target = Path(os.path.normpath(f.parent / os.readlink(f))).relative_to(
                    problem.path / 'data').with_suffix('')

                if target in d.includes or target.parent in d.includes:
                    bar.log(f'Remove linked file {f.name}')
                    f.unlink()

        # Try to remove the directory. Fails if it's not empty.
        try:
            dir_path.rmdir()
            bar.log(f'Remove directory {dir_path.name}')
        except:
            pass

        bar.done()


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

        # Non-standard key. When set, run will be parallelized.
        # Accepts: y/yes/t/true/on/1 and n/no/f/false/off/0 and returns 0 or 1.
        ('parallel', 1, distutils.util.strtobool),
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
                    self.known_cases.add(d.path / Path(include).name)

                d.includes = [Path(include) for include in yaml['include']]


            # Parse child directories/testcases.
            if 'data' in yaml:
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

        self.root_dir.walk(collect_programs, dir_f=None)

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

        # Set generator command, solution, and visualizer for each testcase.
        def set_exec(t):
            if not t.manual:
                t.program.exec = self.generator_commands[t.program.command]
            if t.config.solution:
                t.config.solution.exec = self.solution_commands[t.config.solution.command]
            if t.config.visualizer:
                t.config.visualizer.exec = self.visualizer_commands[t.config.visualizer.command]

        self.root_dir.walk(set_exec, dir_f=None)

        self.input_validators = validate.get_validators(self.problem.path, 'input')
        self.output_validators = validate.get_validators(self.problem.path, 'output')

    def run(self):
        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))

        bar = ProgressBar('Generate', items=item_names)

        if config.args.jobs <= 0:
            warn('Number of jobs is not positive. Disabling parallelization.')

        if config.args.jobs <= 1:
            self.parallel = False

        if not self.parallel:
            self.root_dir.walk(
                lambda t: t.generate(self.problem, self.input_validators, self.output_validators, bar),
                lambda d: d.generate(self.problem, self.known_cases, bar),
            )
        else:
            # Parallelize generating test cases.
            # All testcases are generated in separate threads. Directories are still handled by the
            # main thread. We only start processing a directory after all preceding test cases have
            # completed to avoid problems with including cases.
            q = queue.Queue()

            def worker():
                while True:
                    testcase = q.get()
                    if testcase is None: break
                    testcase.generate(self.problem, self.input_validators, self.output_validators, bar),
                    q.task_done()

            # TODO: Make this a generators.yaml option?
            num_worker_threads = config.args.jobs
            threads = []
            for _ in range(num_worker_threads):
                t = threading.Thread(target=worker)
                t.start()
                threads.append(t)

            def generate_dir(d):
                q.join()
                d.generate(self.problem, self.known_cases, bar)

            try:
                self.root_dir.walk(
                    lambda t: q.put(t),
                    generate_dir,
                )

                q.join()

                for _ in range(num_worker_threads):
                    q.put(None)
                for t in threads:
                    t.join()
            except KeyboardInterrupt:
                for _ in range(num_worker_threads):
                    q.put(None)
                for t in threads:
                    t.join()
                exit(1)

        bar.finalize()

    def clean(self):
        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))

        bar = ProgressBar('Clean', items=item_names)

        self.root_dir.walk(lambda x: x.clean(self.problem, bar),
                           dir_last=True)
        bar.finalize()


def test_generate(problem):
    config = GeneratorConfig(problem)
    config.build()
    config.run()
    return True


def clean(problem):
    config = GeneratorConfig(problem)
    config.clean()
    return True
