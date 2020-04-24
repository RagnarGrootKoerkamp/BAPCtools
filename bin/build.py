import fnmatch
import re
import shutil
import stat
import subprocess

from util import *


# is file at path executable
def _is_executable(path):
    return path.is_file() and (path.stat().st_mode & (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH))


# A function to convert c++ or java to something executable.
# Returns a command to execute and an optional error message.
# This can take either a path to a file (c, c++, java, python) or a directory.
# The directory may contain multiple files.
# This also accepts executable files but will first try to build them anyway using the settings for
# the language.
def build(path):
    # mirror directory structure on tmpfs
    if path.is_absolute():
        outdir = config.tmpdir / path.name
    else:
        outdir = config.tmpdir / path
        if not str(outdir.resolve()).startswith(str(config.tmpdir)):
            outdir = config.tmpdir / path.name

    outdir.mkdir(parents=True, exist_ok=True)

    input_files = list(glob(path, '*')) if path.is_dir() else [path]

    # Check file names.
    for f in input_files:
        if not config.COMPILED_FILE_NAME_REGEX.fullmatch(f.name):
            return (None,
                    f'{cc.red}{str(f)} does not match file name regex {config.FILE_NAME_REGEX}')

    linked_files = []
    if len(input_files) == 0:
        config.n_warn += 1
        return (None, f'{cc.red}{str(path)} is an empty directory.{cc.reset}')

    # Link all input files
    last_input_update = 0
    for f in input_files:
        ensure_symlink(outdir / f.name, f)
        linked_files.append(outdir / f.name)
        last_input_update = max(last_input_update, f.stat().st_ctime)

    runfile = outdir / 'run'

    # Remove all other files.
    for f in outdir.glob('*'):
        if f not in (linked_files + [runfile]):
            if f.is_dir() and not f.is_symlink():
                shutil.rmtree(f)
            else:
                f.unlink()

    # If the run file is up to date, no need to rebuild.
    if runfile.exists() and runfile not in linked_files:
        if not (hasattr(config.args, 'force_build') and config.args.force_build):
            if runfile.stat().st_ctime > last_input_update:
                return ([runfile], None)
        runfile.unlink()

    # If build or run present, use them:
    if _is_executable(outdir / 'build'):
        cur_path = Path.cwd()
        os.chdir(outdir)
        if exec_command(['./build'], memory=5000000000)[0] is not True:
            config.n_error += 1
            os.chdir(cur_path)
            return (None, f'{cc.red}FAILED{cc.reset}')
        os.chdir(cur_path)
        if not _is_executable(outdir / 'run'):
            config.n_error += 1
            return (None, f'{cc.red}FAILED{cc.reset}: {runfile} must be executable')

    # If the run file was provided in the input, just return it.
    if runfile.exists():
        return ([runfile], None)

    # Get language config
    if config.languages is None:
        # Try both contest and repository level.
        if Path('languages.yaml').is_file():
            config.languages = read_yaml(Path('languages.yaml'))
        else:
            config.languages = read_yaml(config.tools_root / 'config/languages.yaml')

        if config.args.cpp_flags:
            config.languages['cpp']['compile'] += config.args.cpp_flags

        config.languages['ctd'] = {
            'name': 'Checktestdata',
            'priority': 1,
            'files': '*.ctd',
            'compile': None,
            'run': 'checktestdata {mainfile}',
        }
        config.languages['viva'] = {
            'name':
            'Viva',
            'priority':
            2,
            'files':
            '*.viva',
            'compile':
            None,
            'run':
            'java -jar {viva_jar} {main_file}'.format(
                viva_jar=config.tools_root / 'support/viva/viva.jar', main_file='{main_file}')
        }

    # Find the best matching language.
    def matches_shebang(f, shebang):
        if shebang is None: return True
        with f.open() as o:
            return shebang.search(o.readline())

    best = (None, [], -1)
    message = None
    for lang in config.languages:
        lang_conf = config.languages[lang]
        globs = lang_conf['files'].split() or []
        shebang = re.compile(lang_conf['shebang']) if lang_conf.get('shebang', None) else None
        priority = int(lang_conf['priority'])

        matching_files = []
        for f in linked_files:
            if any(fnmatch.fnmatch(f, glob) for glob in globs) and matches_shebang(f, shebang):
                matching_files.append(f)

        if (len(matching_files), priority) > (len(best[1]), best[2]):
            best = (lang, matching_files, priority)

        # Make sure c++ does not depend on stdc++.h, because it's not portable.
        if lang == 'cpp':
            for f in matching_files:
                if f.read_text().find('bits/stdc++.h') != -1:
                    if 'validators/' in str(f):
                        config.n_error += 1
                        return (
                            None,
                            f'{cc.red}Validator {str(Path(*f.parts[-2:]))} should not depend on bits/stdc++.h{cc.reset}'
                        )
                    else:
                        message = f'{str(Path(*f.parts[-2:]))} should not depend on bits/stdc++.h{cc.reset}'

    lang, files, priority = best

    if lang is None:
        return (None, f'{cc.red}No language detected for {path}.{cc.reset}')

    if len(files) == 0:
        return (None, f'{cc.red}No file detected for language {lang} at {path}.{cc.reset}')

    mainfile = None
    if len(files) == 1:
        mainfile = files[0]
    else:
        for f in files:
            if f.ascii_lowercse().starts_with('main'):
                mainfile = f
        mainfile = mainfile or sorted(files)[0]

    env = {
        'path': str(outdir),
        # NOTE: This only contains files matching the winning language.
        'files': ''.join(str(f) for f in files),
        'binary': str(runfile),
        'mainfile': str(mainfile),
        'mainclass': str(Path(mainfile).with_suffix('').name),
        'Mainclass': str(Path(mainfile).with_suffix('').name).capitalize(),
        'memlim': get_memory_limit() // 1000000
    }

    # TODO: Support executable files?

    compile_command = config.languages[lang]['compile']
    run_command = config.languages[lang]['run']

    # Prevent building something twice in one invocation of tools.py.
    if compile_command is not None:
        compile_command = compile_command.format(**env).split()
        try:
            ok, err, out = exec_command(
                compile_command,
                stdout=subprocess.PIPE,
                memory=5000000000,
                # Compile errors are never cropped.
                crop=False)
        except FileNotFoundError as err:
            message = f'{cc.red}FAILED{cc.reset} '
            message += '\n' + str(err) + cc.reset
            return (None, message)

        if ok is not True:
            config.n_error += 1
            message = f'{cc.red}FAILED{cc.reset} '
            if err is not None:
                message += '\n' + strip_newline(err) + cc.reset
            if out is not None:
                message += '\n' + strip_newline(out) + cc.reset
            return (None, message)

    if run_command is not None:
        run_command = run_command.format(**env).split()

    return (run_command, message)


# build all files in a directory; return a list of tuples (file, command)
# When 'build' is found, we execute it, and return 'run' as the executable
# This recursively calls itself for subdirectories.
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

        run_command, message = build(path)
        if run_command is not None:
            commands.append((name, run_command))
        if message:
            bar.log(message)
        bar.done()
    if config.verbose:
        print()
    return commands
