import re
import shutil
import stat
import subprocess
import threading

from util import *
from colorama import Fore

EXTRA_LANGUAGES = '''
checktestdata:
    name: 'Checktestdata'
    priority: 1
    files: '*.ctd'
    run: 'checktestdata {mainfile}'

viva:
    name: 'Viva'
    priority: 2
    files: '*.viva'
    run: 'java -jar {viva_jar} {mainfile}'

manual:
    name: 'manual'
    priority: 9999
    files: 'build run'
    compile: '{build}'
    run: '{run}'
'''

# The cached languages.yaml for the current contest.
_languages = None
_languages_lock = threading.Lock()


def languages():
    global _languages, _languages_lock
    with _languages_lock:
        if _languages is not None:
            return _languages

        if Path('languages.yaml').is_file():
            _languages = read_yaml(Path('languages.yaml'))
        else:
            _languages = read_yaml(config.tools_root / 'config/languages.yaml')

        if config.args.cpp_flags:
            _languages['cpp']['compile'] += ' ' + config.args.cpp_flags

        # Add custom languages.
        extra_langs = parse_yaml(EXTRA_LANGUAGES)
        for lang in extra_langs:
            assert lang not in _languages
            _languages[lang] = extra_langs[lang]

        return _languages


# A Program is class that wraps a program (file/directory) on disk. A program is usually one of:
# - a submission
# - a validator
# - a generator
# - a visualizer
#
# Supports two way of calling:
# - Program(path): specify an absolute path, or relative path ('problem/generators/gen.py), and build the
#   file/directory.
# - Program(name, deps): specify a target name ('problem/generators/gen.py') and a list of
#   dependencies (must be Path objects).
#
# Member variables are:
# - path:           source file/directory
# - short_path:     the path relative to problem/subdir/, or None
# - tmpdir:        the build directory in tmpfs. This is only created when build() is called.
# - input_files:    list of source files linked into tmpdir
# - language:       the detected language
# - env:            the environment variables used for compile/run command substitution
# - timestamp:      time of last change to the source files
#
# After build() has been called, the following are available:
# - run_command:    command to be executed. E.g. ['/path/to/run'] or ['python3', '/path/to/main.py']. `None` if something failed.
#
# build() will return the (run_command, message) pair.
class Program:
    def __init__(
        self, problem, path, deps=None, *, skip_double_build_warning=False, check_constraints=False
    ):
        if deps is not None:
            assert isinstance(self, Generator)
            assert isinstance(deps, list)
            assert len(deps) > 0

        assert not self.__class__ is Program

        # Make sure we never try to build the same program twice. That'd be stupid.
        if not skip_double_build_warning:
            if path in problem._programs:
                error(f'Why would you build {path} twice?')
                assert path not in problem._programs
            problem._programs[path] = self

        self.bar = None
        self.path = path
        self.problem = problem

        # Set self.name and self.tmpdir.
        # Ideally they are the same as the path inside the problem, but fallback to just the name.
        try:
            # Only resolve the parent of the program. This preserves programs that are symlinks to other directories.
            relpath = (path.parent.resolve() / path.name).relative_to(
                problem.path.resolve() / self.subdir
            )
            self.short_path = relpath
            self.name = str(relpath)
            self.tmpdir = problem.tmpdir / self.subdir / relpath
        except ValueError as e:
            self.short_path = Path(path.name)
            self.name = str(path.name)
            self.tmpdir = problem.tmpdir / self.subdir / path.name

        if check_constraints:
            self.tmpdir = self.tmpdir.parent / (self.tmpdir.name + '_check_constraints')

        self.compile_command = None
        self.check_constraints = check_constraints
        self.run_command = None
        self.timestamp = None
        self.env = {}

        self.ok = True
        self.built = False

        # Detect language, dependencies, and main file
        if deps:
            self.source_files = deps
            self.has_deps = True
        else:
            if path.is_dir():
                self.source_files = list(glob(path, '*'))
                # Filter out __pycache__ files.
                self.source_files = list(
                    filter(lambda f: f.name != '__pycache__', self.source_files)
                )
            elif path.is_file():
                self.source_files = [path]
            else:
                self.source_files = []
            self.has_deps = False

    # is file at path executable
    @staticmethod
    def _is_executable(path):
        return path.is_file() and (
            path.stat().st_mode & (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        )

    # Returns true when file f matches the given shebang regex.
    @staticmethod
    def _matches_shebang(f, shebang):
        if shebang is None:
            return True
        with f.open() as o:
            return shebang.search(o.readline())

    # Do not warn for the same fallback language multiple times.
    warn_cache = set()

    # Sets self.language and self.env['mainfile']
    def _get_language(self, deps=None):
        # language, matching files, priority
        best = (None, [], 0)
        message = None
        fallback = False
        candidates = []
        for lang in languages():
            lang_conf = languages()[lang]
            name = lang_conf['name']
            globs = lang_conf['files'].split() or []
            shebang = re.compile(lang_conf['shebang']) if lang_conf.get('shebang') else None
            priority = int(lang_conf['priority'])

            matching_files = []
            for f in self.input_files:
                if any(f.match(glob) for glob in globs) and Program._matches_shebang(f, shebang):
                    matching_files.append(f)

            if len(matching_files) == 0:
                continue

            candidates.append(
                (priority // 1000, len(matching_files), priority, lang, matching_files)
            )
        candidates.sort(reverse=True)

        for _, _, priority, lang, files in candidates:
            # Make sure we can run programs for this language.
            if 'compile' in lang_conf:
                exe = lang_conf['compile'].split()[0]
                if exe[0] != '{' and shutil.which(exe) == None:
                    if best[0] is None or priority >= best[2]:
                        fallback = True
                        if exe not in Program.warn_cache:
                            if config.args.verbose:
                                self.bar.debug(
                                    f'Compile program {exe} not found for language {name}. Falling back to lower priority languages.'
                                )
                                Program.warn_cache.add(exe)
                    continue
            assert 'run' in lang_conf
            exe = lang_conf['run'].split()[0]
            if exe[0] != '{' and shutil.which(exe) == None:
                fallback = True
                if best[0] is None or priority >= best[2]:
                    if exe not in Program.warn_cache:
                        if config.args.verbose:
                            Program.warn_cache.add(exe)
                            self.bar.debug(
                                f'Run program {exe} not found for language {name}. Falling back to lower priority languages.'
                            )
                continue

            if fallback:
                if lang not in Program.warn_cache:
                    if config.args.verbose:
                        Program.warn_cache.add(lang)
                        self.bar.debug(f'Falling back to {languages()[lang]["name"]}.')

            if len(files) == 0:
                self.ok = False
                self.bar.error(f'No file detected for language {name} at {self.path}.')
                return False

            self.language = lang
            mainfile = None
            if not self.has_deps:
                if len(files) == 1:
                    mainfile = files[0]
                else:
                    for f in files:
                        if f.name.lower().startswith('main'):
                            mainfile = f
                    mainfile = mainfile or sorted(files)[0]
            else:
                mainfile = self.tmpdir / deps[0].name

            mainclass = str(mainfile.with_suffix('').name)
            self.env = {
                'path': str(self.tmpdir),
                # NOTE: This only contains files matching the winning language.
                'files': ' '.join(str(f) for f in files),
                'binary': self.tmpdir / 'run',
                'mainfile': str(mainfile),
                'mainclass': mainclass,
                'Mainclass': mainclass[0].upper() + mainclass[1:],
                # Memory limit in MB.
                'memlim': (get_memory_limit() or 1024),
                # Out-of-spec variables used by 'manual' and 'Viva' languages.
                'build': self.tmpdir / 'build'
                if (self.tmpdir / 'build') in self.input_files
                else '',
                'run': self.tmpdir / 'run',
                'viva_jar': config.tools_root / 'third_party/viva/viva.jar',
            }

            return True

        # The for loop did not find a suitable language.
        self.ok = False
        self.bar.error(f'No language detected for {self.path}.')
        return False

    def _checks(self):
        # Make sure c++ does not depend on stdc++.h, because it's not portable.
        if self.language == 'cpp':
            for f in self.source_files:
                try:
                    if f.read_text().find('bits/stdc++.h') != -1:
                        if 'validators/' in str(f):
                            self.bar.error(f'Must not depend on bits/stdc++.h.')
                            break
                        else:
                            self.bar.log(f'Should not depend on bits/stdc++.h')
                            break
                except UnicodeDecodeError:
                    pass

        # Warn for known bad (non-deterministic) patterns in generators
        from validate import Validator

        if isinstance(self, Generator) or isinstance(self, Validator):
            if self.language == 'cpp':
                for f in self.source_files:
                    try:
                        text = f.read_text()
                        bad_random = set()
                        for s in [
                            'rand\\(\\)',
                            'uniform_int_distribution',
                            'uniform_real_distribution',
                            'normal_distribution',
                            'exponential_distribution',
                            'geometric_distribution',
                            'binomial_distribution',
                            'random_device',
                            'default_random_engine',
                        ]:
                            for line in text.splitlines():
                                if s in line and 'bt ignore' not in line:
                                    bad_random.add(s)
                        if bad_random:
                            bad_message = ', '.join(bad_random)
                            self.bar.warn(
                                f'Calling {bad_message} in {f.name} is implementation dependent in C++. Use <validation.h> instead, or add `// bt ignore` to the line.'
                            )
                        if text.find('typeid(') != -1:
                            self.bar.warn(
                                f'Calling typeid() in {f.name} is implementation dependent in C++.'
                            )
                    except UnicodeDecodeError:
                        pass
            if 'py' in self.language:
                for f in self.source_files:
                    try:
                        text = f.read_text()
                        for s in ['list(set(']:
                            if text.find(s) != -1:
                                self.bar.warn(
                                    f'The order of sets is not fixed across implementations. Please sort the list!'
                                )
                    except UnicodeDecodeError:
                        pass

    # Return True on success.
    def _compile(self):
        meta_path = self.tmpdir / 'meta_'

        # Remove all non-source files.
        for f in self.tmpdir.glob('*'):
            if f not in (self.input_files + [meta_path]):
                if f.is_dir() and not f.is_symlink():
                    shutil.rmtree(f)
                else:
                    f.unlink()

        # The case where compile_command='{build}' will result in an empty list here.
        if not self.compile_command:
            return True

        try:
            ret = exec_command(
                self.compile_command,
                stdout=subprocess.PIPE,
                memory=5_000_000_000,
                cwd=self.tmpdir,
                # Compile errors are never cropped.
                crop=False,
            )
        except FileNotFoundError as err:
            self.ok = False
            self.bar.error('Failed', str(err))
            return False

        if ret.ok is not True:
            data = ''
            if ret.err is not None:
                data += strip_newline(ret.err) + '\n'
            if ret.out is not None:
                data += strip_newline(ret.out) + '\n'
            self.ok = False
            self.bar.error('Failed', data)
            return False

        meta_path.write_text(' '.join(self.compile_command))
        return True

    # Return True on success, False on failure.
    def build(self, bar):
        assert not self.built
        self.built = True

        if not self.ok:
            return False
        self.bar = bar

        if len(self.source_files) == 0:
            self.ok = False
            if self.path.is_dir():
                self.bar.error(f'{self.short_path} is an empty directory.')
            else:
                self.bar.error(f'{self.path} does not exist.')
            return False

        # Check file names.
        for f in self.source_files:
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(f.name):
                self.ok = False
                self.bar.error(f'{str(f)} does not match file name regex {config.FILE_NAME_REGEX}')
                return False

        # Link all source_files
        if self.tmpdir.is_file():
            self.tmpdir.unlink()
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.timestamp = 0
        self.input_files = []
        for f in self.source_files:
            ensure_symlink(self.tmpdir / f.name, f)
            self.input_files.append(self.tmpdir / f.name)
            self.timestamp = max(self.timestamp, f.stat().st_mtime)

        if not self._get_language(self.source_files):
            return False

        self._checks()

        # A file containing the compile command. Timestamp is used as last build time.
        meta_path = self.tmpdir / 'meta_'

        lang_config = languages()[self.language]

        compile_command = lang_config['compile'] if 'compile' in lang_config else ''
        if self.check_constraints and self.language == 'cpp':
            compile_command += ' -Duse_source_location'
        self.compile_command = compile_command.format(**self.env).split()
        run_command = lang_config['run']
        self.run_command = run_command.format(**self.env).split()

        # Compare the latest source timestamp (self.timestamp) to the last build.
        up_to_date = (
            meta_path.is_file()
            and meta_path.stat().st_mtime >= self.timestamp
            and meta_path.read_text() == ' '.join(self.compile_command)
        )

        if not up_to_date or config.args.force_build:
            if not self._compile():
                return False

        if self.path in self.problem._program_callbacks:
            for c in self.problem._program_callbacks[self.path]:
                c(self)
        return True

    @staticmethod
    def add_callback(problem, path, c):
        if path not in problem._program_callbacks:
            problem._program_callbacks[path] = []
        problem._program_callbacks[path].append(c)


class Generator(Program):
    subdir = 'generators'

    # Run the generator in the given working directory.
    # May write files in |cwd| and stdout is piped to {name}.in if it's not written already.
    # Returns ExecResult. Success when result.ok is True.
    def run(self, bar, cwd, name, args=[]):
        assert self.run_command is not None

        in_path = cwd / (name + '.in')
        stdout_path = cwd / (name + '.in_')

        # Clean the directory, but not the meta_ file.
        for f in cwd.iterdir():
            if f.name in ['meta_', 'meta_.yaml']:
                continue
            if f.is_dir() and not f.is_symlink():
                shutil.rmtree(f)
            else:
                f.unlink()

        timeout = config.get_timeout()

        with stdout_path.open('w') as stdout_file:
            result = exec_command(
                self.run_command + args, stdout=stdout_file, timeout=timeout, cwd=cwd
            )

        result.retry = False

        if result.ok == -9:
            # Timeout -> stop retrying and fail.
            bar.log(f'TIMEOUT after {timeout}s', color=Fore.RED)
            return result

        if result.ok is not True:
            # Other error -> try again.
            result.retry = True
            return result

        if stdout_path.read_text():
            if in_path.is_file():
                bar.warn(f'Generator wrote to both {name}.in and stdout. Ignoring stdout.')
            else:
                stdout_path.rename(in_path)
        else:
            if not in_path.is_file():
                bar.log(f'Did not write {name}.in and stdout is empty!', color=Fore.RED)
                result.ok = False
                return result

        return result


class Visualizer(Program):
    subdir = 'visualizers'

    # Run the visualizer.
    # Stdin and stdout are not used.
    def run(self, cwd, args=[]):
        assert self.run_command is not None
        return exec_command(self.run_command + args, timeout=config.get_timeout(), cwd=cwd)
