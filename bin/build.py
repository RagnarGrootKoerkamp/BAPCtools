import fnmatch
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


# TODO: Store compile command in the temporary Program directory, so we can detect if the compilation command changes.

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
# - tmp_dir:        the build directory in tmpfs. This is only created when build() is called.
# - input_files:    list of source files linked into tmp_dir
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

    def __init__(self, path, deps=None, *, bar):
        if deps is not None:
            assert isinstance(deps, list)
            assert len(deps) > 0

        # Make sure we never try to build the same program twice. That'd be stupid.
        assert path not in Program._cache
        Program._cache[path] = self

        self.bar = bar
        self.path = path
        self.tmp_dir = Program._get_tmp_dir(path)
        self.compile_command = None
        self.run_command = None
        self.timestamp = None
        self.env = {}

        self.ok = True
        self.built = False

        # Detect language, dependencies, and main file
        if deps: source_files = deps
        else: source_files = list(glob(path, '*')) if path.is_dir() else [path]

        # Check file names.
        for f in source_files:
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(f.name):
                self.ok = False
                self.bar.error(f'{str(f)} does not match file name regex {config.FILE_NAME_REGEX}')
                return

        if len(source_files) == 0:
            self.ok = False
            self.bar.error('{str(path)} is an empty directory.')
            return

        # Link all source_files
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = 0
        self.input_files = []
        for f in source_files:
            ensure_symlink(self.tmp_dir / f.name, f)
            self.input_files.append(self.tmp_dir / f.name)
            self.timestamp = max(self.timestamp, f.stat().st_ctime)

        self._get_language(deps)

    # Make a path in tmpfs. Usually this will be e.g. config.tmpdir/problem/submissions/accepted/sol.py.
    # For absolute paths and weird relative paths, fall back to config.tmpdir/sol.py.
    def _get_tmp_dir(path):
        # For a single file/directory: make a new directory in tmpfs and link all files into that dir.
        # For a given list of dependencies: make a new directory and link the given dependencies.
        if path.is_absolute():
            return config.tmpdir / path.name
        else:
            outdir = config.tmpdir / path
            if not str(outdir.resolve()).startswith(str(config.tmpdir)):
                return config.tmpdir / path.name
            return outdir

    # is file at path executable
    def _is_executable(path):
        return path.is_file() and (path.stat().st_mode &
                                   (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH))

    # Returns true when file f matches the given shebang regex.
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
                if any(fnmatch.fnmatch(f.name, glob)
                       for glob in globs) and Program._matches_shebang(f, shebang):
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
            mainfile = self.tmp_dir / deps[0].name

        self.env = {
            'path': str(self.tmp_dir),
            # NOTE: This only contains files matching the winning language.
            'files': ' '.join(str(f) for f in files),
            'binary': self.tmp_dir / 'run',
            'mainfile': str(mainfile),
            'mainclass': str(mainfile.with_suffix('').name),
            'Mainclass': str(mainfile.with_suffix('').name).capitalize(),
            'memlim': get_memory_limit() // 1000000,

            # Out-of-spec variables used by 'manual' and 'Viva' languages.
            'build': self.tmp_dir / 'build' if
            (self.tmp_dir / 'build') in self.input_files else '',
            'run': self.tmp_dir / 'run',
            'viva_jar': config.tools_root / 'support/viva/viva.jar',
        }

        # Make sure c++ does not depend on stdc++.h, because it's not portable.
        if lang == 'cpp':
            for f in files:
                if f.read_text().find('bits/stdc++.h') != -1:
                    if 'validators/' in str(f):
                        bar.error(f'Validator {str(Path(*f.parts[-2:]))} should not depend on bits/stdc++.h.')
                        return None
                    else:
                        bar.warn(f'{str(Path(*f.parts[-2:]))} should not depend on bits/stdc++.h')

    # Return True on success.
    def _compile(self):
        meta_path = self.tmp_dir / 'meta_'

        # Remove all non-source files.
        for f in self.tmp_dir.glob('*'):
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
                cwd=self.tmp_dir,
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


    # Return run_command, or None if building failed.
    def build(self):
        if not self.ok: return None
        assert not self.built
        self.built = True

        # A file containing the compile command. Timestamp is used as last build time.
        meta_path = self.tmp_dir / 'meta_'

        lang_config = languages()[self.language]

        compile_command = lang_config['compile'] if 'compile' in lang_config else ''
        self.compile_command = compile_command.format(**self.env).split()
        run_command = lang_config['run']
        self.run_command = run_command.format(**self.env).split()

        # Compare the latest source timestamp (self.timestamp) to the last build.
        up_to_date = meta_path.is_file() and meta_path.stat().st_ctime >= self.timestamp and meta_path.read_text() == ' '.join(self.compile_command)

        if not up_to_date or config.args.force_build:
            if not self._compile(): return None

        if self.path in Program._callbacks:
            for c in Program._callbacks[self.path]: c(self)
        return self.run_command


    def add_callback(path, c):
        if path not in Program._callbacks: Program._callbacks[path] = []
        Program._callbacks[path].append(c)

    def get(path):
        return Program._cache[path]

# build all files in a directory; return a list of tuples (program name, command)
def build_programs(programs, include_dirname=False):
    if len(programs) == 0:
        return []
    bar = ProgressBar('Building', items=[print_name(path) for path in programs])

    commands = []
    for path in programs:
        bar.start(print_name(path))

        if include_dirname:
            dirname = path.parent.name
            name = Path(dirname) / path.name
        else:
            name = path.name

        run_command = Program(path, bar=bar).build()
        if run_command is not None: commands.append((name, run_command))
        bar.done()
    if config.verbose:
        print()
    return commands
