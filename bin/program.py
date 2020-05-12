import re
import shutil
import stat
import subprocess

from util import *

EXTRA_LANGUAGES = '''
ctd:
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


def languages():
    global _languages
    if _languages is not None: return _languages
    if Path('languages.yaml').is_file():
        _languages = read_yaml(Path('languages.yaml'))
    else:
        _languages = read_yaml(config.tools_root / 'config/languages.yaml')

    if config.args.cpp_flags:
        _languages['cpp']['compile'] += ' ' + config.args.cpp_flags

    # Add custom languages.
    extra_langs = yaml.safe_load(EXTRA_LANGUAGES)
    for lang in extra_langs:
        assert lang not in _languages
        _languages[lang] = extra_langs[lang]

    return _languages


# TODO: Migrate Validators to Program class.
# TODO: Run submissions for interactive problems.

# A Program is class that wraps a program (file/directory) on disk. A program is usually one of:
# - a submission
# - a validator
# - a generator
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
    # A map from program paths to callbacks to be called on build() completion.
    _callbacks = dict()
    # A map from program paths to corresponding Program instances.
    _cache = dict()

    def __init__(self, problem, path, deps=None):
        if deps is not None:
            print(self, problem, path, deps)
            assert isinstance(deps, list)
            assert len(deps) > 0

        assert not self.__class__ is Program

        # Make sure we never try to build the same program twice. That'd be stupid.
        assert path not in problem._programs
        problem._programs[path] = self

        self.bar = None
        self.path = path
        self.problem = problem

        # Set self.name and self.tmpdir.
        # Ideally they are the same as the path inside the problem, but fallback to just the name.
        try:
            relpath = path.resolve().relative_to(problem.path.resolve() / self.subdir)
            self.short_path = relpath
            self.name = str(relpath)
            self.tmpdir = problem.tmpdir / self.subdir / relpath
        except ValueError as e:
            self.short_path = path.name
            self.name = str(path.name)
            self.tmpdir = problem.tmpdir / self.subdir / path.name


        self.compile_command = None
        self.run_command = None
        self.timestamp = None
        self.env = {}

        self.ok = True
        self.built = False

        # Detect language, dependencies, and main file
        if deps: self.source_files = deps
        else: self.source_files = list(glob(path, '*')) if path.is_dir() else [path]

    # is file at path executable
    @staticmethod
    def _is_executable(path):
        return path.is_file() and (path.stat().st_mode &
                                   (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH))

    # Returns true when file f matches the given shebang regex.
    @staticmethod
    def _matches_shebang(f, shebang):
        if shebang is None: return True
        with f.open() as o:
            return shebang.search(o.readline())

    # Sets self.language and self.env['mainfile']
    def _get_language(self, deps=None):
        # language, matching files, priority
        best = (None, [], 0)
        message = None
        for lang in languages():
            lang_conf = languages()[lang]
            globs = lang_conf['files'].split() or []
            shebang = re.compile(lang_conf['shebang']) if lang_conf.get('shebang', None) else None
            priority = int(lang_conf['priority'])

            matching_files = []
            for f in self.input_files:
                if any(f.match(glob) for glob in globs) and Program._matches_shebang(f, shebang):
                    matching_files.append(f)

            if len(matching_files) == 0: continue

            if (len(matching_files), priority) > (len(best[1]), best[2]):
                best = (lang, matching_files, priority)

        lang, files, priority = best

        if lang is None:
            self.ok = False
            self.bar.error(f'No language detected for {self.path}.')
            return

        if len(files) == 0:
            self.ok = False
            self.bar.error(f'No file detected for language {lang} at {self.path}.')
            return

        self.language = lang
        mainfile = None
        if deps is None:
            if len(files) == 1:
                mainfile = files[0]
            else:
                for f in files:
                    if f.name.lower().startswith('main'):
                        mainfile = f
                mainfile = mainfile or sorted(files)[0]
        else:
            mainfile = self.tmpdir / deps[0].name

        self.env = {
            'path': str(self.tmpdir),
            # NOTE: This only contains files matching the winning language.
            'files': ' '.join(str(f) for f in files),
            'binary': self.tmpdir / 'run',
            'mainfile': str(mainfile),
            'mainclass': str(mainfile.with_suffix('').name),
            'Mainclass': str(mainfile.with_suffix('').name).capitalize(),
            'memlim': get_memory_limit() // 1000000,

            # Out-of-spec variables used by 'manual' and 'Viva' languages.
            'build': self.tmpdir / 'build' if
            (self.tmpdir / 'build') in self.input_files else '',
            'run': self.tmpdir / 'run',
            'viva_jar': config.tools_root / 'support/viva/viva.jar',
        }

        # Make sure c++ does not depend on stdc++.h, because it's not portable.
        if lang == 'cpp':
            for f in files:
                if f.read_text().find('bits/stdc++.h') != -1:
                    if 'validators/' in str(f):
                        bar.error(
                            f'Validator {str(Path(*f.parts[-2:]))} should not depend on bits/stdc++.h.'
                        )
                        return None
                    else:
                        bar.warn(f'{str(Path(*f.parts[-2:]))} should not depend on bits/stdc++.h')

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
        if not self.compile_command: return True

        try:
            ok, err, out = exec_command(
                self.compile_command,
                stdout=subprocess.PIPE,
                memory=5000000000,
                cwd=self.tmpdir,
                # Compile errors are never cropped.
                crop=False)
        except FileNotFoundError as err:
            self.ok = False
            self.bar.error('FAILED', str(err))
            return False

        if ok is not True:
            data = ''
            if err is not None: data += strip_newline(err) + '\n'
            if out is not None: data += strip_newline(out) + '\n'
            self.ok = False
            self.bar.error('FAILED', data)
            return False

        meta_path.write_text(' '.join(self.compile_command))
        return True

    # Return True on success, False on failure.
    def build(self, bar):
        assert not self.built
        self.built = True

        if not self.ok: return False
        self.bar = bar


        if len(self.source_files) == 0:
            self.ok = False
            self.bar.error('{str(path)} is an empty directory.')
            return

        # Check file names.
        for f in self.source_files:
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(f.name):
                self.ok = False
                self.bar.error(f'{str(f)} does not match file name regex {config.FILE_NAME_REGEX}')
                return

        # Link all source_files
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.timestamp = 0
        self.input_files = []
        for f in self.source_files:
            ensure_symlink(self.tmpdir / f.name, f)
            self.input_files.append(self.tmpdir / f.name)
            self.timestamp = max(self.timestamp, f.stat().st_ctime)

        self._get_language(self.source_files)


        # A file containing the compile command. Timestamp is used as last build time.
        meta_path = self.tmpdir / 'meta_'

        lang_config = languages()[self.language]

        compile_command = lang_config['compile'] if 'compile' in lang_config else ''
        self.compile_command = compile_command.format(**self.env).split()
        run_command = lang_config['run']
        self.run_command = run_command.format(**self.env).split()

        # Compare the latest source timestamp (self.timestamp) to the last build.
        up_to_date = meta_path.is_file(
        ) and meta_path.stat().st_ctime >= self.timestamp and meta_path.read_text() == ' '.join(
            self.compile_command)

        if not up_to_date or config.args.force_build:
            if not self._compile(): return False

        if self.path in self.problem._program_callbacks:
            for c in self.problem._program_callbacks[self.path]:
                c(self)
        return True

    @staticmethod
    def add_callback(problem, path, c):
        if path not in problem._programs: problem._program_callbacks[path] = []
        problem._program_callbacks[path].append(c)



class Generator(Program):
    subdir = 'generators'
    #def __init__(self, problem, path): super().__init__(problem, path)

    # Run the generator in the given working directory.
    # May write files in |cwd| and stdout is piped to {name}.in if it's not written already.
    # Returns ExecResult. Success when result.ok is True.
    def run(self, cwd, name, args=[]):
        assert self.run_command is not None

        in_path = cwd / (name + '.in')
        stdout_path = cwd / (name + '.in_')

        # Clean the directory.
        for f in cwd.iterdir():
            f.unlink()

        with stdout_path.open('w') as stdout_file:
            result = exec_command_2(self.run_command + args, stdout=stdout_file, timeout=config.timeout(), cwd=cwd)

        result.retry = False

        if result.ok == -9:
            # Timeout -> stop retrying and fail.
            self.bar.error(f'TIMEOUT after {timeout}s')
            return result

        if result.ok is not True:
            # Other error -> try again.
            result.retry = True
            return result

        if in_path.is_file():
            if stdout_path.read_text():
                self.bar.warn(f'Generator wrote to both {name}.in and stdout. Ignoring stdout.')
        else:
            if not stdout_path.is_file():
                self.bar.error(f'Did not write {name}.in and stdout is empty!')
                result.ok = False
                return result

        if stdout_path.is_file():
            stdout_path.rename(in_path)

        return result

class Visualizer(Program):
    subdir = 'visualizers'
    #def __init__(self, problem, path): super().__init__(problem, path)

    # Run the visualizer.
    # Stdin and stdout are not used.
    def run(self, cwd, args=[]):
        assert self.run_command is not None
        return exec_command_2(self.run_command + args, timeout=config.timeout(), cwd=cwd)
