#!/usr/bin/python3
# PYTHON_ARGCOMPLETE_OK
"""Can be run on multiple levels:

    - from the root of the git repository
    - from a contest directory
    - from a problem directory
the tool will know where it is (by looking for the .git directory) and run on
everything inside it

- Ragnar Groot Koerkamp

Parts of this are copied from/based on run_program.py, written by Raymond van
Bommel.
"""

import sys
import shlex
import stat
import hashlib
import argparse
import argcomplete  # For automatic shell completions
import os
import datetime
import time
import re
import shutil
import subprocess
import resource
import time
import yaml
import configparser
import io
import zipfile
import hashlib
from pathlib import Path

# Local imports
import config
from objects import *
import export
import latex
import util
import validation
from util import ProgressBar, _c, glob, warn, error, fatal


# Get the list of relevant problems.
# Either use the problems.yaml, or check the existence of problem.yaml and sort
# by shortname.
def get_problems():
    # TODO: Rename 'contest' to 'problemset'?

    def is_problem_directory(path):
        # TODO: Simplify this when problem.yaml is required.
        return (path / 'problem.yaml').is_file() or (path / 'problem_statement').is_dir()

    contest = None
    problem = None
    level = None
    if hasattr(config.args, 'contest') and config.args.contest:
        contest = config.args.contest
        os.chdir(contest)
        level = 'contest'
    elif hasattr(config.args, 'problem') and config.args.problem:
        problem = Path(config.args.problem)
        level = 'problem'
        os.chdir(problem.parent)
    elif is_problem_directory(Path('.')):
        problem = Path().cwd()
        level = 'problem'
        os.chdir('..')
    else:
        level = 'contest'

    problems = []
    if level == 'problem':
        # TODO: look for a problems.yaml file above here and find a letter?
        problems = [Problem(Path(problem.name))]
    else:
        level = 'contest'
        # If problemset.yaml is available, use it.
        problemsyaml = Path('problems.yaml')
        if problemsyaml.is_file():
            # TODO: Implement label default value
            problemlist = util.read_yaml(problemsyaml)
            assert problemlist is not None
            labels = set()
            nextlabel = 'A'
            problems = []
            for p in problemlist:
                label = nextlabel
                if 'label' in p: label = p['label']
                assert label != ''
                nextlabel = label[:-1] + chr(ord(label[-1]) + 1)
                # TODO: Print a nice error instead using some error() util.
                assert label not in labels
                labels.add(label)
                problems.append(Problem(Path(p['id']), label))
        else:
            # Otherwise, fallback to all directories with a problem.yaml and sort by
            # shortname.
            # TODO: Keep this fallback?
            label_ord = 0
            for path in glob(Path('.'), '*/'):
                if is_problem_directory(path):
                    label = chr(ord('A') + label_ord)
                    problems.append(Problem(path, label))
                    label_ord += 1

    contest = Path().cwd().name

    # We create one tmpdir per repository, assuming the repository is one level
    # higher than the contest directory.
    if config.tmpdir is None:
        h = hashlib.sha256(bytes(Path().cwd().parent)).hexdigest()[-6:]
        config.tmpdir = Path('/tmp/bapctools_' + h)
        config.tmpdir.mkdir(parents=True, exist_ok=True)

    return (problems, level, contest)


# is file at path executable
def is_executable(path):
    return path.is_file() and (path.stat().st_mode & (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH))


# Look at the shebang at the first line of the file to choose between python 2
# and python 3.
def python_version(path):
    if util.is_windows(): return 'Python'

    shebang = path.read_text().split('\n')[0]
    if re.match('^#!.*python2', shebang):
        return 'python2'
    if re.match('^#!.*python3', shebang):
        return 'python3'
    return 'python2'


def python_interpreter(version):
    if hasattr(config.args, 'pypy') and config.args.pypy:
        if version == 'python2':
            if shutil.which('pypy') is not None:
                return 'pypy'
            else:
                print('\n' + _c.orange + 'pypy executable not found, falling back to python2' +
                      _c.reset)
        if version == 'python3':
            if shutil.which('pypy3') is not None:
                return 'pypy3'
            else:
                print('\n' + _c.orange + 'pypy3 executable not found, falling back to python3' +
                      _c.reset)
    return version


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

    # Link all input files
    input_files = list(path.glob('*')) if path.is_dir() else [path]
    linked_files = []
    if len(input_files) == 0:
        config.n_warn += 1
        return (None, f'{_c.red}{str(path)} is an empty directory.{_c.reset}')

    last_input_update = 0
    for f in input_files:
        latex.ensure_symlink(outdir / f.name, f)
        linked_files.append(outdir / f.name)
        last_input_update = max(last_input_update, f.stat().st_ctime)

    runfile = outdir / 'run'

    # Remove all other files.
    for f in outdir.glob('*'):
        if f not in (linked_files + [runfile]):
            f.unlink()

    # If the run file is up to date, no need to rebuild.
    if runfile.exists() and runfile not in linked_files:
        if not (hasattr(config.args, 'force_build') and config.args.force_build):
            if runfile.stat().st_ctime > last_input_update:
                return ([runfile], None)
        runfile.unlink()

    # If build or run present, use them:
    if is_executable(outdir / 'build'):
        cur_path = Path.cwd()
        os.chdir(outdir)
        if util.exec_command(['./build'], memory=5000000000)[0] is not True:
            config.n_error += 1
            os.chdir(cur_path)
            return (None, f'{_c.red}FAILED{_c.reset}')
        os.chdir(cur_path)
        if not is_executable(outdir / 'run'):
            config.n_error += 1
            return (None, f'{_c.red}FAILED{_c.reset}: {runfile} must be executable')

    # If the run file was provided in the input, just return it.
    if runfile.exists():
        return ([runfile], None)

    # Otherwise, detect the language and entry point and build manually.
    language_code = None
    main_file = None if path.is_dir() else outdir / path.name
    c_files = []
    for f in input_files:
        e = f.suffix

        lang = None
        main = False

        message = ''

        if e in ['.c']:
            lang = 'c'
            main = True
            c_files.append(outdir / f.name)
        if e in ['.cc', '.cpp', '.cxx.', '.c++', '.C']:
            lang = 'cpp'
            main = True
            c_files.append(outdir / f.name)

            # Make sure c++ does not depend on stdc++.h, because it's not portable.
            if 'validators/' in str(f) and f.read_text().find('bits/stdc++.h') != -1:
                config.n_warn += 1
                message = f'{_c.orange}{print_name(f)} should not depend on bits/stdc++.h{_c.reset}'

        if e in ['.java']:
            lang = 'java'
            main = f.name == 'Main.java'
        if e in ['.kt']:
            lang = 'kt'
            # TODO: this probably isn't correct, but fine until it breaks.
            main = True
        if e in ['.py', '.py2', '.py3']:
            if e == '.py2':
                lang = 'python2'
            elif e == '.py3':
                lang = 'python3'
            elif e == '.py':
                lang = python_version(path)
            main = f.name == 'main.py'
        if e in ['.ctd']:
            lang = 'ctd'
            main = True
        if e in ['.viva']:
            lang = 'viva'
            main = True

        if language_code is not None and lang is not None and lang != language_code:
            config.n_error += 1
            msg = (f'{_c.red}Could not build {path}: found conflicting languages '
                   f'{language_code} and {lang}!{_c.reset}')
            return (None, msg)

        if language_code is None:
            language_code = lang

        if main_file is not None and main and main_file != outdir / f.name and language_code != 'cpp':
            config.n_error += 1
            msg = (f'{_c.red}Could not build {path}: found conflicting main files '
                   f'{main_file.name} and {f.name}!{_c.reset}')
            return (None, msg)
        if main_file is None and main:
            main_file = outdir / f.name

    # Check if the file itself is executable.
    if language_code is None and main_file is not None and is_executable(main_file):
        return ([main_file], None)

    if language_code is None:
        config.n_error += 1
        return (None, f'{_c.red}No language detected for {path}.{_c.reset}')

    compile_command = None
    run_command = None

    if language_code == 'c':
        compile_command = [
            'gcc', '-I', config.tools_root / 'headers', '-std=c11', '-Wall', '-O2', '-o', runfile
        ] + c_files + ['-lm']
        run_command = [runfile]
    elif language_code == 'cpp':
        compile_command = ([
            'g++',
            '-I',
            config.tools_root / 'headers',
            '-std=c++14',
            '-Wall',
            '-O2',
            '-fdiagnostics-color=always',  # Enable color output
            '-o',
            runfile,
            main_file
        ] + ([] if config.args.cpp_flags is None else config.args.cpp_flags.split()))
        run_command = [runfile]
    elif language_code == 'java':
        compile_command = ['javac', '-d', outdir, main_file]
        run_command = [
            'java',
            '-enableassertions',
            '-XX:+UseSerialGC',
            '-Xss64M',  # Max stack size
            '-Xms1024M',  # Initial heap size
            '-Xmx1024M',  # Max heap size
            '-cp',
            outdir,
            main_file.stem
        ]
    elif language_code == 'kt':
        if shutil.which('kotlinc') is None:
            run_command = None
            config.n_error += 1
            message = f'{_c.red}kotlinc executable not found in PATH{_c.reset}'
        else:
            jarfile = runfile.with_suffix('.jar')
            compile_command = ['kotlinc', '-d', jarfile, '-include-runtime', main_file]
            run_command = [
                'java',
                '-enableassertions',
                '-XX:+UseSerialGC',
                '-Xss64M',  # Max stack size
                '-Xms1024M',  # Initial heap size
                '-Xmx1024M',  # Max heap size
                '-jar',
                jarfile
            ]
    elif language_code in ['python2', 'python3', 'python', 'Python']:
        run_command = [python_interpreter(language_code), main_file]
    elif language_code == 'ctd':
        ctd_executable = shutil.which('checktestdata')
        if ctd_executable is None:
            run_command = None
            config.n_error += 1
            message = f'{_c.red}checktestdata executable not found in PATH{_c.reset}'
        else:
            run_command = [ctd_executable, main_file]
    elif language_code == 'viva':
        viva_jar = config.tools_root / 'support/viva/viva.jar'
        if not viva_jar.is_file():
            run_command = None
            config.n_error += 1
            message = f'{_c.red}viva.jar not found{_c.reset}'
        else:
            run_command = ['java', '-jar', viva_jar, main_file]
    else:

        config.n_error += 1
        return (None, f'{_c.red}Unknown language \'{language_code}\' at file {path}{_c.reset}')

    # Prevent building something twice in one invocation of tools.py.
    if compile_command is not None:
        ok, err, out = util.exec_command(compile_command,
                                         stdout=subprocess.PIPE,
                                         memory=5000000000)
        if ok is not True:
            config.n_error += 1
            message = f'{_c.red}FAILED{_c.reset} '
            if err is not None:
                message += '\n' + util.strip_newline(err) + _c.reset
            if out is not None:
                message += '\n' + util.strip_newline(out) + _c.reset
            run_command = None

    if run_command is None and message == '':
        config.n_error += 1
        message = f'{_c.red}FAILED{_c.reset}'
    return (run_command, message)


# build all files in a directory; return a list of tuples (file, command)
# When 'build' is found, we execute it, and return 'run' as the executable
# This recursively calls itself for subdirectories.
def build_programs(programs, include_dirname=False):
    if len(programs) == 0:
        return []
    max_file_len = max(len(print_name(path)) for path in programs)
    bar = ProgressBar('Building', max_file_len, len(programs))

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


# Drops the first two path components <problem>/<type>/
def print_name(path, keep_type=False):
    return str(Path(*path.parts[1 if keep_type else 2:]))


# If check_constraints is True, this chooses the first validator that matches
# contains 'constraints_file' in its source.
def get_validators(problem, validator_type, check_constraints=False):
    files = (glob(problem / (validator_type + '_validators'), '*') +
             glob(problem / (validator_type + '_format_validators'), '*'))

    def has_constraints_checking(f):
        return 'constraints_file' in f.read_text()

    if check_constraints:
        for f in files:
            if f.is_file(): sources = [f]
            elif f.is_dir(): sources = glob(f, '**/*')
            has_constraints = False
            for s in sources:
                if has_constraints_checking(s):
                    has_constraints = True
                    break
            if has_constraints:
                files = [f]
                break

    if hasattr(config.args, 'validator') and config.args.validator:
        files = [problem / config.args.validator]

    validators = build_programs(files)

    if len(validators) == 0:
        error(f'\nAborting: At least one {validator_type} validator is needed!')

    return validators


# Validate the .in and .ans files for a problem.
# For input:
# - build+run or all files in input_validators
#
# For output:
# - 'default' validation:
#   build+run or all files in output_validators
# - 'custom'  validation:
#   none, .ans file not needed.
#
# We always pass both the case_sensitive and space_change_sensitive flags.
def validate(problem, validator_type, settings, printnewline=False, check_constraints=False):
    assert validator_type in ['input', 'output']

    #if validator_type == 'output' and settings.validation == 'custom':
    #return True

    if check_constraints:
        if not config.args.cpp_flags:
            config.args.cpp_flags = ''
        config.args.cpp_flags += ' -Duse_source_location'

        validators = get_validators(problem, validator_type, check_constraints=True)
    else:
        validators = get_validators(problem, validator_type)

    if len(validators) == 0:
        return False

    testcases = util.get_testcases(problem, validator_type == 'output')

    # Get the bad testcases:
    # For input validation, look for .in files without .ans or .out.
    # For output validator, look for .in files with a .ans or .out.
    for f in glob(problem, 'data/bad/**/*.in'):
        has_ans = f.with_suffix('.ans').is_file()
        has_out = f.with_suffix('.out').is_file()
        if validator_type == 'input':
            # This will only be marked 'bad' if there is no .ans or .out.
            testcases.append(f)
        if validator_type == 'output' and (has_ans or has_out):
            testcases.append(f)

    if len(testcases) == 0:
        return True

    ext = '.in' if validator_type == 'input' else '.ans'
    action = 'Validating ' + validator_type

    # Flags are only needed for output validators; input validators are
    # sensitive by default.
    flags = []
    if validator_type == 'output':
        flags = ['case_sensitive', 'space_change_sensitive']

    success = True
    max_testcase_len = max([len(print_name(testcase) + ext) for testcase in testcases])

    constraints = {}

    # validate the testcases
    bar = ProgressBar(action, max_testcase_len, len(testcases))
    for testcase in testcases:
        bar.start(print_name(testcase.with_suffix(ext)))

        bad_testcase = False
        if validator_type == 'input':
            bad_testcase = 'data/bad/' in str(testcase) and not testcase.with_suffix(
                '.ans').is_file() and not testcase.with_suffix('.out').is_file()

        if validator_type == 'output':
            bad_testcase = 'data/bad/' in str(testcase)

        main_file = testcase.with_suffix(ext)
        if bad_testcase and validator_type == 'output' and main_file.with_suffix('.out').is_file():
            main_file = testcase.with_suffix('.out')

        for validator in validators:
            # simple `program < test.in` for input validation and ctd output validation
            if Path(validator[0]).suffix == '.ctd':
                ok, err, out = util.exec_command(
                    validator[1],
                    # TODO: Can we make this more generic? CTD returning 0 instead of 42
                    # is a bit annoying.
                    expect=1 if bad_testcase else 0,
                    stdin=main_file.open())

            elif Path(validator[0]).suffix == '.viva':
                # Called as `viva validator.viva testcase.in`.
                ok, err, out = util.exec_command(
                    validator[1] + [main_file],
                    # TODO: Can we make this more generic? VIVA returning 0 instead of 42
                    # is a bit annoying.
                    expect=1 if bad_testcase else 0)
                # Slightly hacky: CTD prints testcase errors on stderr while VIVA prints
                # them on stdout.
                err = out

            elif validator_type == 'input':

                constraints_file = config.tmpdir / 'constraints'
                if constraints_file.is_file():
                    constraints_file.unlink()

                ok, err, out = util.exec_command(
                    # TODO: Store constraints per problem.
                    validator[1] + flags +
                    (['--constraints_file', constraints_file] if check_constraints else []),
                    expect=config.RTV_WA if bad_testcase else config.RTV_AC,
                    stdin=main_file.open())

                # Merge with previous constraints.
                if constraints_file.is_file():
                    for line in constraints_file.read_text().splitlines():
                        loc, has_low, has_high, vmin, vmax, low, high = line.split()
                        has_low = bool(int(has_low))
                        has_high = bool(int(has_high))
                        try:
                            vmin = int(vmin)
                        except:
                            vmin = float(vmin)
                        try:
                            vmax = int(vmax)
                        except:
                            vmax = float(vmax)
                        if loc in constraints:
                            c = constraints[loc]
                            has_low |= c[0]
                            has_high |= c[1]
                            if c[2] < vmin:
                                vmin = c[2]
                                low = c[4]
                            if c[3] > vmax:
                                vmax = c[3]
                                high = c[5]
                        constraints[loc] = (has_low, has_high, vmin, vmax, low, high)

                    constraints_file.unlink()

            else:
                # more general `program test.in test.ans feedbackdir < test.in/ans` output validation otherwise
                ok, err, out = util.exec_command(
                    validator[1] +
                    [testcase.with_suffix('.in'),
                     testcase.with_suffix('.ans'), config.tmpdir] + flags,
                    expect=config.RTV_WA if bad_testcase else config.RTV_AC,
                    stdin=main_file.open())

            print_message = config.verbose > 0
            message = ''

            # Failure?
            if ok is True:
                message = _c.green + 'PASSED ' + validator[0] + _c.reset
            else:
                config.n_error += 1
                message = _c.red + 'FAILED ' + validator[0] + _c.reset
                print_message = True
                success = False

            # Print stdout and stderr whenever something is printed
            if err:
                prefix = '  '
                if err.count('\n') > 1:
                    prefix = '\n'
                message += prefix + _c.orange + util.strip_newline(err) + _c.reset
            # Print stdout when -e is set. (But not on normal failures.)
            if out and config.args.error:
                prefix = '  '
                if out.count('\n') > 1:
                    prefix = '\n'
                message += f'\n{_c.red}VALIDATOR STDOUT{_c.reset}' + prefix + _c.orange + util.strip_newline(
                    out) + _c.reset

            if print_message:
                if not config.verbose and printnewline:
                    bar.clearline()
                    printnewline = False
                    print()
                bar.log(message)

                # Move testcase to destination directory if specified.
                if hasattr(config.args, 'move_to') and config.args.move_to:
                    bar.log(_c.orange + 'MOVING TESTCASE' + _c.reset)
                    targetdir = problem / config.args.move_to
                    targetdir.mkdir(parents=True, exist_ok=True)
                    testcase.rename(targetdir / testcase.name)
                    ansfile = testcase.with_suffix('.ans')
                    ansfile.rename(targetdir / ansfile.name)
                    break

                # Remove testcase if specified.
                elif validator_type == 'input' and hasattr(config.args,
                                                           'remove') and config.args.remove:
                    bar.log(_c.red + 'REMOVING TESTCASE!' + _c.reset)
                    if testcase.exists():
                        testcase.unlink()
                    if testcase.with_suffix('.ans').exists():
                        testcase.with_suffix('.ans').unlink()
                    break

        bar.done()

    # Make sure all constraints are satisfied.
    for loc, value in sorted(constraints.items()):
        loc = Path(loc).name
        has_low, has_high, vmin, vmax, low, high = value
        if not has_low:
            warn(
                f'BOUND NOT REACHED: The value at {loc} was never equal to the lower bound of {low}. Min value found: {vmin}'
            )
        if not has_high:
            warn(
                f'BOUND NOT REACHED: The value at {loc} was never equal to the upper bound of {high}. Max value found: {vmax}'
            )
        success = False

    if not config.verbose and success:
        print(ProgressBar.action(action, f'{_c.green}Done{_c.reset}'))
        if validator_type == 'output':
            print()
    else:
        print()

    return success


# This prints the number belonging to the count.
# This can be a red/white colored number, or Y/N
def get_stat(count, threshold=True, upper_bound=None):
    if threshold is True:
        if count >= 1:
            return _c.white + 'Y' + _c.reset
        else:
            return _c.red + 'N' + _c.reset
    color = _c.white
    if upper_bound != None and count > upper_bound:
        color = _c.orange
    if count < threshold:
        color = _c.red
    return color + str(count) + _c.reset


def stats(problems):
    stats = [
        # Roughly in order of importance
        ('yaml', 'problem.yaml'),
        ('ini', 'domjudge-problem.ini'),
        ('tex', 'problem_statement/problem*.tex'),
        ('sol', 'problem_statement/solution.tex'),
        ('   Ival', ['input_validators/*', 'input_format_validators/*']),
        ('Oval', ['output_validators/*']),
        ('   sample', 'data/sample/*.in', 2),
        ('secret', 'data/secret/**/*.in', 15, 50),
        ('   AC', 'submissions/accepted/*', 3),
        (' WA', 'submissions/wrong_answer/*', 2),
        ('TLE', 'submissions/time_limit_exceeded/*', 1),
        ('   cpp', [
            'submissions/accepted/*.c', 'submissions/accepted/*.cpp', 'submissions/accepted/*.cc'
        ], 1),
        ('java', 'submissions/accepted/*.java', 1),
        ('py2', ['submissions/accepted/*.py', 'submissions/accepted/*.py2'], 1),
        ('py3', 'submissions/accepted/*.py3', 1),
    ]

    headers = ['problem'] + [h[0] for h in stats] + ['  comment']
    cumulative = [0] * (len(stats))

    header_string = ''
    format_string = ''
    for header in headers:
        if header in ['problem', 'comment']:
            width = len(header)
            for problem in problems:
                width = max(width, len(problem.label + ' ' + problem.id))
            header_string += '{:<' + str(width) + '}'
            format_string += '{:<' + str(width) + '}'
        else:
            width = len(header)
            header_string += ' {:>' + str(width) + '}'
            format_string += ' {:>' + str(width + len(_c.white) + len(_c.reset)) + '}'

    header = header_string.format(*headers)
    print(_c.bold + header + _c.reset)

    for problem in problems:

        def count(path):
            if type(path) is list:
                return sum(count(p) for p in path)
            cnt = 0
            for p in glob(problem.path, path):
                # Exclude files containing 'TODO: Remove'.
                if p.is_file():
                    with p.open() as file:
                        data = file.read()
                        if data.find('TODO: Remove') == -1:
                            cnt += 1
                if p.is_dir():
                    ok = True
                    for f in glob(p, '*'):
                        if f.is_file():
                            with f.open() as file:
                                data = file.read()
                                if data.find('TODO') != -1:
                                    ok = False
                                    break
                    if ok:
                        cnt += 1
            return cnt

        counts = [count(s[1]) for s in stats]
        for i in range(0, len(stats)):
            cumulative[i] = cumulative[i] + counts[i]

        verified = False
        comment = ''
        if 'verified' in problem.config:
            verified = bool(problem.config['verified'])
        if 'comment' in problem.config:
            comment = problem.config['comment']

        if verified: comment = _c.green + comment + _c.reset
        else: comment = _c.orange + comment + _c.reset

        print(
            format_string.format(
                problem.label + ' ' + problem.id, *[
                    get_stat(counts[i], True if len(stats[i]) <= 2 else stats[i][2],
                             None if len(stats[i]) <= 3 else stats[i][3])
                    for i in range(len(stats))
                ], comment))

    # print the cumulative count
    print('-' * len(header))
    print(
        format_string.format(*(['TOTAL'] + list(map(lambda x: get_stat(x, False), cumulative)) +
                               [''])))


# returns a map {answer type -> [(name, command)]}
def get_submissions(problem):

    programs = []

    if hasattr(config.args, 'submissions') and config.args.submissions:
        for submission in config.args.submissions:
            if Path(problem / submission).parent == problem / 'submissions':
                programs += glob(problem / submission, '*')
            else:
                programs.append(problem / submission)
    else:
        for verdict in config.PROBLEM_OUTCOMES:
            programs += glob(problem, f'submissions/{verdict.lower()}/*')

    run_commands = build_programs(programs, True)
    submissions = {
        'ACCEPTED': [],
        'WRONG_ANSWER': [],
        'TIME_LIMIT_EXCEEDED': [],
        'RUN_TIME_ERROR': []
    }
    for c in run_commands:
        submissions[get_submission_type(c[0])].append(c)

    return submissions


# Return (ret, timeout (True/False), duration)
def run_testcase(run_command, testcase, outfile, tle=None, crop=True):
    if hasattr(config.args, 'timeout') and config.args.timeout:
        timeout = float(config.args.timeout)
    elif tle:
        # Double the tle to check for solutions close to the required bound
        # ret = True or ret = (code, error)
        timeout = 2 * tle
    else:
        timeout = None

    with testcase.with_suffix('.in').open('rb') as inf:

        def run(outfile):
            did_timeout = False
            tstart = time.monotonic()
            try:
                if outfile is None:
                    # Print both stdout and stderr directly to the terminal.
                    ok, err, out = util.exec_command(run_command,
                                                     expect=0,
                                                     crop=crop,
                                                     stdin=inf,
                                                     stdout=None,
                                                     stderr=None,
                                                     timeout=timeout)
                else:
                    ok, err, out = util.exec_command(run_command,
                                                     expect=0,
                                                     crop=crop,
                                                     stdin=inf,
                                                     stdout=outfile,
                                                     timeout=timeout)
            except subprocess.TimeoutExpired:
                did_timeout = True
                ok, err, out = (True, None, None)
            tend = time.monotonic()

            if tle is not None and tend - tstart > tle:
                did_timeout = True
            return ok, did_timeout, tend - tstart, err, out

        if outfile is None:
            return run(outfile)
        else:
            return run(outfile.open('wb'))


# return (verdict, time, remark)
def process_interactive_testcase(run_command,
                                 testcase,
                                 outfile,
                                 settings,
                                 output_validators,
                                 printnewline=False):
    if len(output_validators) != 1:
        error(
            'Interactive problems need exactly one output validator. Found {len(output_validators)}.'
        )
    output_validator = output_validators[0]

    # Compute the timeouts
    validator_timeout = 60

    if hasattr(config.args, 'timeout') and config.args.timeout:
        submission_timeout = float(config.args.timeout)
    elif settings.timelimit:
        # Double the tle to check for solutions close to the required bound
        # ret = True or ret = (code, error)
        submission_timeout = 2 * settings.timelimit
    else:
        submission_timeout = 60

    # Set up pipes.
    # Run the validator
    flags = []
    if settings.space_change_sensitive: flags += ['space_change_sensitive']
    if settings.case_sensitive: flags += ['case_sensitive']

    judgepath = config.tmpdir / 'judge'
    judgepath.mkdir(parents=True, exist_ok=True)

    def setlimits():
        resource.setrlimit(resource.RLIMIT_CPU, (validator_timeout, validator_timeout))

    # Start the validator.
    validator_process = subprocess.Popen(
        output_validator[1] +
        [testcase.with_suffix('.in'),
         testcase.with_suffix('.ans'), judgepath] + flags,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=setlimits,
        bufsize=2**20)

    # Start and time the submission.
    tstart = time.monotonic()
    ok, err, out = util.exec_command(run_command,
                                     expect=0,
                                     stdin=validator_process.stdout,
                                     stdout=validator_process.stdin,
                                     stderr=subprocess.PIPE,
                                     timeout=submission_timeout)

    # Wait
    (validator_out, validator_err) = validator_process.communicate()

    tend = time.monotonic()

    did_timeout = False
    if settings.timelimit is not None and tend - tstart > settings.timelimit:
        did_timeout = True

    validator_ok = validator_process.returncode

    if validator_ok != config.RTV_AC and validator_ok != config.RTV_WA:
        config.n_error += 1
        verdict = 'VALIDATOR_CRASH'
    elif did_timeout:
        verdict = 'TIME_LIMIT_EXCEEDED'
    elif ok is not True:
        verdict = 'RUN_TIME_ERROR'
    elif validator_ok == config.RTV_WA:
        verdict = 'WRONG_ANSWER'
    elif validator_ok == config.RTV_AC:
        verdict = 'ACCEPTED'

    return (verdict, tend - tstart, validator_err.decode('utf-8'), err)


# return (verdict, time, remark)
def process_testcase(run_command,
                     testcase,
                     outfile,
                     settings,
                     output_validators,
                     printnewline=False):

    if settings.validation == 'interactive':
        return process_interactive_testcase(run_command, testcase, outfile, settings,
                                            output_validators)

    ok, timeout, duration, err, out = run_testcase(run_command, testcase, outfile,
                                                   settings.timelimit)
    verdict = None
    if timeout:
        verdict = 'TIME_LIMIT_EXCEEDED'
    elif ok is not True:
        verdict = 'RUN_TIME_ERROR'
        err = 'Exited with code ' + str(ok) + ':\n' + err
    else:
        assert settings.validation in ['default', 'custom']
        if settings.validation == 'default':
            ok, err, out = validation.default_output_validator(testcase.with_suffix('.ans'),
                                                               outfile, settings)
        elif settings.validation == 'custom':
            ok, err, out = validation.custom_output_validator(testcase, outfile, settings,
                                                              output_validators)

        if ok is True:
            verdict = 'ACCEPTED'
        elif ok is False:
            verdict = 'WRONG_ANSWER'
        else:
            config.n_error += 1
            verdict = 'VALIDATOR_CRASH'
            #err = err

    return (verdict, duration, err, out)


# program is of the form (name, command)
# return outcome
# always: failed submissions
# -v: all programs and their results (+failed testcases when expected is 'accepted')
def run_submission(submission,
                   testcases,
                   settings,
                   output_validators,
                   max_submission_len,
                   expected='ACCEPTED',
                   table_dict=None):
    need_newline = config.verbose == 1

    time_total = 0
    time_max = 0
    testcase_max_time = None

    action = 'Running ' + str(submission[0])
    max_total_length = max(
        max([len(print_name(testcase.with_suffix('')))
             for testcase in testcases]), 15) + max_submission_len
    max_testcase_len = max_total_length - len(str(submission[0]))

    printed = False
    bar = ProgressBar(action, max_testcase_len, len(testcases))

    final_verdict = 'ACCEPTED'
    for testcase in testcases:
        bar.start(print_name(testcase.with_suffix('')))
        outfile = config.tmpdir / 'test.out'
        verdict, runtime, err, out = process_testcase(submission[1], testcase, outfile, settings,
                                                      output_validators, need_newline)

        if config.PRIORITY[verdict] > config.PRIORITY[final_verdict]:
            final_verdict = verdict

        # Manage timings, table data, and print output
        time_total += runtime
        if runtime > time_max:
            time_max = runtime
            testcase_max_time = print_name(testcase.with_suffix(''))

        if table_dict is not None:
            table_dict[testcase] = verdict == 'ACCEPTED'

        got_expected = verdict == 'ACCEPTED' or verdict == expected
        color = _c.green if got_expected else _c.red
        print_message = config.verbose > 0 or (not got_expected
                                               and verdict != 'TIME_LIMIT_EXCEEDED')
        message = '{:6.3f}s '.format(runtime) + color + verdict + _c.reset

        # Print stderr whenever something is printed
        if err:
            prefix = '  '
            if err.count('\n') > 1:
                prefix = '\n'
            message += prefix + _c.orange + util.strip_newline(err) + _c.reset

        # Print stdout when -e is set.
        if out and (verdict == 'VALIDATOR_CRASH' or config.args.error):
            prefix = '  '
            if out.count('\n') > 1:
                prefix = '\n'
            output_type = 'STDOUT'
            if settings.validation == 'interactive': output_type = 'PROGRAM STDERR'
            message += f'\n{_c.red}{output_type}{_c.reset}' + prefix + _c.orange + util.strip_newline(
                out) + _c.reset

        if print_message:
            bar.log(message)
            printed = True

        bar.done()

        if not config.verbose and verdict in config.MAX_PRIORITY_VERDICT:
            break

    # Use a bold summary line if things were printed before.
    if printed:
        color = _c.boldgreen if final_verdict == expected else _c.boldred
    else:
        color = _c.green if final_verdict == expected else _c.red

    time_avg = time_total / len(testcases)

    # Print summary line
    boldcolor = _c.bold if printed else ''
    print(
        f'{action:<{max_total_length-6}} {boldcolor}max/avg {time_max:6.3f}s {time_avg:6.3f}s {color}{final_verdict:<20}{_c.reset} @ {testcase_max_time}'
    )

    if config.verbose:
        print()

    return final_verdict == expected


def get_submission_type(s):
    ls = str(s).lower()
    if 'wrong_answer' in ls:
        return 'WRONG_ANSWER'
    if 'time_limit_exceeded' in ls:
        return 'TIME_LIMIT_EXCEEDED'
    if 'run_time_error' in ls:
        return 'RUN_TIME_ERROR'
    return 'ACCEPTED'


# return true if all submissions for this problem pass the tests
def run_submissions(problem, settings):
    needans = True
    if settings.validation == 'interactive': needans = False
    testcases = util.get_testcases(problem, needans=needans)

    if len(testcases) == 0:
        warn('No testcases found!')
        return False

    output_validators = None
    if settings.validation in ['custom', 'interactive']:
        output_validators = get_validators(problem, 'output')
        if len(output_validators) == 0:
            return False

    #if hasattr(config.args, 'timelimit') and config.args.timelimit is not None:
    #settings.timelimit = float(config.args.timelimit)

    submissions = get_submissions(problem)

    max_submission_len = max([0] +
                             [len(str(x[0])) for cat in submissions for x in submissions[cat]])

    success = True
    verdict_table = []
    for verdict in submissions:
        for submission in submissions[verdict]:
            verdict_table.append(dict())
            success &= run_submission(submission,
                                      testcases,
                                      settings,
                                      output_validators,
                                      max_submission_len,
                                      verdict,
                                      table_dict=verdict_table[-1])

    if hasattr(settings, 'table') and settings.table:
        # Begin by aggregating bitstrings for all testcases, and find bitstrings occurring often (>=config.TABLE_THRESHOLD).
        def single_verdict(row, testcase):
            if testcase in row:
                if row[testcase]:
                    return _c.green + '1' + _c.reset
                else:
                    return _c.red + '0' + _c.reset
            else:
                return '-'

        make_verdict = lambda tc: ''.join(map(lambda row: single_verdict(row, tc), verdict_table))
        resultant_count, resultant_id = dict(), dict()
        special_id = 0
        for testcase in testcases:
            resultant = make_verdict(testcase)
            if resultant not in resultant_count:
                resultant_count[resultant] = 0
            resultant_count[resultant] += 1
            if resultant_count[resultant] == config.TABLE_THRESHOLD:
                special_id += 1
                resultant_id[resultant] = special_id

        scores = {}
        for t in testcases:
            scores[t] = 0
        for dct in verdict_table:
            failures = 0
            for t in dct:
                if not dct[t]:
                    failures += 1
            for t in dct:
                if not dct[t]:
                    scores[t] += 1. / failures
        scores_list = sorted(scores.values())

        print('\nVerdict analysis table. Submissions are ordered as above. Higher '
              'scores indicate they are critical to break some submissions.')
        for testcase in testcases:
            # Skip all AC testcases
            if all(map(lambda row: row[testcase], verdict_table)): continue

            color = _c.reset
            if len(scores_list) > 6 and scores[testcase] >= scores_list[-6]:
                color = _c.orange
            if len(scores_list) > 3 and scores[testcase] >= scores_list[-3]:
                color = _c.red
            print(f'{str(testcase):<60}', end=' ')
            resultant = make_verdict(testcase)
            print(resultant, end='  ')
            print(f'{color}{scores[testcase]:0.3f}{_c.reset}  ', end='')
            if resultant in resultant_id:
                print(str.format('(Type {})', resultant_id[resultant]), end='')
            print(end='\n')

    return success


def test_submission(submission, testcases, settings):
    print(ProgressBar.action('Running', str(submission[0])))

    timeout = settings.timelimit
    if hasattr(config.args, 'timeout') and config.args.timeout:
        timeout = float(config.args.timeout)
    for testcase in testcases:
        header = ProgressBar.action('Running ' + str(submission[0]), str(testcase.with_suffix('')))
        print(header)
        outfile = config.tmpdir / 'test.out'
        # err and out should be None because they go to the terminal.
        ok, did_timeout, duration, err, out = run_testcase(submission[1],
                                                           testcase,
                                                           outfile=None,
                                                           tle=timeout,
                                                           crop=False)
        assert err is None and out is None
        if ok is not True:
            config.n_error += 1
            print(
                f'{_c.red}Run time error!{_c.reset} exit code {ok} {_c.bold}{duration:6.3f}s{_c.reset}'
            )
        elif did_timeout:
            config.n_error += 1
            print(f'{_c.red}Aborted!{_c.reset} {_c.bold}{duration:6.3f}s{_c.reset}')
        else:
            print(f'{_c.green}Done:{_c.reset} {_c.bold}{duration:6.3f}s{_c.reset}')
        print()


# Takes a list of submissions and runs them against the chosen testcases.
# Instead of validating the output, this function just prints all output to the
# terminal.
# Note: The CLI only accepts one submission.
def test_submissions(problem, settings):
    testcases = util.get_testcases(problem, needans=False)

    if len(testcases) == 0:
        warn('No testcases found!')
        return False

    submissions = get_submissions(problem)

    verdict_table = []
    for verdict in submissions:
        for submission in submissions[verdict]:
            test_submission(submission, testcases, settings)
    return True


# Return config, generator_runs pair
def parse_gen_yaml(problem):
    yaml_path = problem / 'generators' / 'gen.yaml'
    if not yaml_path.is_file():
        error(f'{yaml_path} not found!')
        return None, {}

    yaml_data = yaml.safe_load(yaml_path.read_text())

    gen_config = None
    if 'config' in yaml_data:
        gen_config = yaml_data['config']
        del yaml_data['config']

    # path -> [commands]
    generator_runs = {}

    def parse_yaml(prefix, m):
        for key in m:
            if prefix / key in generator_runs:
                warn(f'Duplicate generator key {prefix/key}.')
            if m[key] is None:
                # manual testcase
                continue
            if isinstance(m[key], dict):
                parse_yaml(prefix / key, m[key])
                continue
            if isinstance(m[key], list):
                generator_runs[prefix / key] = m[key]
                continue
            if isinstance(m[key], str):
                generator_runs[prefix / key] = [m[key]]
                continue
            error(f'Could not parse generator value for key {key}: {m[key]}')

    parse_yaml(Path(''), yaml_data)

    # Filter for the given paths.
    if hasattr(config.args, 'generators') and config.args.generators != []:

        def drop_data(p):
            return p[5:] if p.startswith('data/') else p

        prefixes = tuple(drop_data(p) for p in config.args.generators)
        new_runs = {}
        for path in generator_runs:
            if str(path).startswith(prefixes):
                new_runs[path] = generator_runs[path]
        generator_runs = new_runs

    return gen_config, generator_runs


# Run generators according to the gen.yaml file.
def generate(problem, settings):
    gen_config, generator_runs = parse_gen_yaml(problem)

    generate_ans = False
    submission = None
    if gen_config:
        if 'generate_ans' in gen_config:
            generate_ans = gen_config['generate_ans']
        if generate_ans and 'submission' in gen_config:
            submission = gen_config['submission']
            if not submission:
                error(f'Submission should not be empty!')

    if len(generator_runs) == 0: return True

    if generate_ans and submission is not None:
        submission_path = problem / submission
        if not (submission_path.is_file() or submission_path.is_dir()):
            error(f'Submission not found: {submission_path}')
            submission = None
        else:
            submission, msg = build(problem / submission)
            if submission is None:
                error(msg)

    max_testcase_len = max([len(str(key)) for key in generator_runs]) + 1

    bar = ProgressBar('Generate', max_testcase_len, len(generator_runs))

    nskip = 0
    nfail = 0

    tmpdir = config.tmpdir / problem.name / 'generate'
    tmpdir.mkdir(parents=True, exist_ok=True)

    for file_name in generator_runs:
        commands = generator_runs[file_name]

        bar.start(str(file_name))

        (problem / 'data' / file_name.parent).mkdir(parents=True, exist_ok=True)

        # Clean the directory.
        for f in tmpdir.iterdir():
            f.unlink()

        stdin_path = tmpdir / file_name.name
        stdout_path = tmpdir / (file_name.name + '.stdout')

        # Run all commands.
        for command in commands:
            input_command = shlex.split(command)

            generator_name = input_command[0]
            input_args = input_command[1:]

            for i in range(len(input_args)):
                x = input_args[i]
                if x == '$SEED':
                    val = int(hashlib.sha512(command.encode('utf-8')).hexdigest(), 16) % (2**31)
                    input_args[i] = val

            generator_command, msg = build(problem / 'generators' / generator_name)
            if generator_command is None:
                error(msg)
                break

            command = generator_command + input_args

            stdout_file = stdout_path.open('w')
            stdin_file = stdin_path.open('r') if stdin_path.is_file() else None
            ok, err, out = util.exec_command(command,
                                             stdout=stdout_file,
                                             stdin=stdin_file,
                                             cwd=tmpdir)
            stdout_file.close()
            if stdin_file: stdin_file.close()

            if stdout_path.is_file():
                shutil.move(stdout_path, stdin_path)

            if ok is not True:
                bar.error('FAILED')
                nfail += 1
                ok = False
                break

        def maybe_move(source, target):
            same = True
            if target.is_file():
                if source.read_text() != target.read_text():
                    same = False
                    if hasattr(settings, 'force') and settings.force:
                        shutil.move(source, target)
                        bar.log('CHANGED: ' + target.name)
                    else:
                        nskip += 1
                        bar.warn('SKIPPED: ' + target.name + _c.reset + '; supply -f to overwrite')
            else:
                same = False
                shutil.move(source, target)
                bar.log('NEW: ' + target.name)
            return same

        # Copy all generated files back to the data directory.
        for f in tmpdir.iterdir():
            if f.stat().st_size == 0: continue

            target = problem / 'data' / file_name.parent / f.name

            # Generate .ans for .in files.
            if f.suffix == '.in' and generate_ans and submission:
                ansfile = f.with_suffix('.ans')
                ok, timeout, duration, err, out = run_testcase(submission, f, ansfile,
                                                               settings.timelimit)
                if not ok:
                    bar.error('.ans FAILED')
                else:
                    ok &= maybe_move(ansfile, target.with_suffix('.ans'))

            # Move the .in.
            ok &= maybe_move(f, target)

        bar.done(ok)

    if not config.verbose and nskip == 0 and nfail == 0:
        print(ProgressBar.action('Generate', f'{_c.green}Done{_c.reset}'))

    print()
    return nskip == 0 and nfail == 0


# Remove all files mentioned in the gen.yaml file.
def clean(problem):
    gen_config, generator_runs = parse_gen_yaml(problem)
    for file_path in generator_runs:
        f = problem / 'data' / file_path
        if f.is_file():
            print(ProgressBar.action('REMOVE', str(f)))
            f.unlink()

        ansfile = f.with_suffix('.ans')

        if ansfile.is_file():
            print(ProgressBar.action('REMOVE', str(ansfile)))
            ansfile.unlink()

        try:
            f.parent.rmdir()
        except:
            pass

    return True


# Use a compatible input validator to generate random testcases.
def generate_random_input(problem, settings):
    # Find the right validator
    validators = get_validators(problem, 'input')
    if len(validators) == 0:
        return False

    if len(validators) != 1:
        error('Choosing a default validator failed. Use --validator <validator> instead.')
        return False
    validator = validators[0]

    testcases = [(problem / x).with_suffix('.in') for x in settings.testcases]

    max_testcase_len = max([len(print_name(testcase, True)) for testcase in testcases])

    bar = ProgressBar('Generate', max_testcase_len, len(testcases))

    nskip = 0
    nfail = 0
    for testcase in testcases:
        bar.start(print_name(testcase, True))

        if testcase.exists() and not (hasattr(settings, 'force') and settings.force):
            message = _c.red + 'SKIPPED' + _c.reset + '; file already exists. -f to overwrite'
            nskip += 1
        else:
            success = False
            for retry in range(settings.retries):
                if testcase.exists():
                    testcase.unlink()
                ok, err, out = util.exec_command(
                    validator[1] + ['--generate'],
                    expect=config.RTV_AC,
                    stdout=testcase.open('w'),
                    #stderr=None
                )

                if ok == True:
                    message = _c.green + 'WRITTEN' + _c.reset
                    success = True
                    break
                else:
                    message = err
                    if testcase.exists() and not (hasattr(settings, 'keep') and settings.keep):
                        testcase.unlink()
                    nskip += 1

            if not success and retry == settings.retries - 1:
                nfail += 1
                message = _c.red + 'GENERATION FAILED' + _c.reset + ': ' + f'All {settings.retries} attempts failed. Try --retries <num>.' + '\n' + message

        bar.done(False, message)

    if not config.verbose and nskip == 0 and nfail == 0:
        print(ProgressBar.action('Generate', f'{_c.green}Done{_c.reset}'))

    print()
    return nskip == 0 and nfail == 0


def generate_answer(problem, settings):
    if hasattr(settings, 'submission') and settings.submission:
        submission = problem / settings.submission
    else:
        # only get one accepted submission
        submissions = list(glob(problem, 'submissions/accepted/*'))
        if len(submissions) == 0:
            print('No submission found for this problem!')
            sys.exit(1)
        submissions.sort()
        # Look fora c++ solution if available.
        submission = None
        for s in submissions:
            # Skip files containing 'NO_GENERATE'.
            # Pick files containing 'CANONICAL'.
            with open(s) as submission_file:
                text = submission_file.read()
                if text.find('NO_GENERATE') != -1:
                    continue
                if text.find('CANONICAL') != -1:
                    submission = s
                    break
            if s.suffix == '.cpp':
                submission = s
            else:
                if submission is None:
                    submission = s

    # build submission
    bar = ProgressBar('Building')
    bar.start(str(submission))
    bar.log()
    run_command, message = build(submission)
    if run_command is None:
        print(bar.log(message))
        return False

    if config.verbose:
        print()

    testcases = util.get_testcases(problem, needans=False)

    nsame = 0
    nchange = 0
    nskip = 0
    nnew = 0
    nfail = 0

    max_testcase_len = max(
        [len(print_name(testcase.with_suffix('.ans'))) for testcase in testcases])

    bar = ProgressBar('Generate', max_testcase_len, len(testcases))

    for testcase in testcases:
        bar.start(print_name(testcase.with_suffix('.ans')))

        outfile = config.tmpdir / 'test.out'
        try:
            outfile.unlink()
        except OSError:
            pass

        # Ignore stdout and stderr from the program.
        ok, timeout, duration, err, out = run_testcase(run_command, testcase, outfile,
                                                       settings.timelimit)
        message = ''
        same = False
        if ok is not True or timeout is True:
            message = 'FAILED'
            nfail += 1
        else:
            if testcase.with_suffix('.ans').is_file():
                compare_settings = argparse.Namespace()
                compare_settings.__dict__.update({
                    'case_sensitive': True,
                    'space_change_sensitive': True,
                    'floatabs': None,
                    'floatrel': None
                })
                if validation.default_output_validator(testcase.with_suffix('.ans'), outfile,
                                                       compare_settings)[0]:
                    same = True
                    nsame += 1
                else:
                    if hasattr(settings, 'force') and settings.force:
                        if (hasattr(settings, 'samples')
                                and settings.samples) or 'sample' not in str(testcase):
                            shutil.move(outfile, testcase.with_suffix('.ans'))
                            nchange += 1
                            message = 'CHANGED'
                        else:
                            message = _c.orange + 'SKIPPED' + _c.reset + '; supply -f --samples to overwrite'
                    else:
                        nskip += 1
                        message = _c.red + 'SKIPPED' + _c.reset + '; supply -f to overwrite'
            else:
                shutil.move(outfile, testcase.with_suffix('.ans'))
                nnew += 1
                message = 'NEW'

        bar.done(same, message)

    if not config.verbose and nskip == 0 and nfail == 0:
        print(ProgressBar.action('Generate', f'{_c.green}Done{_c.reset}'))

    print()
    return nskip == 0 and nfail == 0


def print_sorted(problems):
    prefix = config.args.contest + '/' if config.args.contest else ''
    for problem in problems:
        print(f'{problem.label:<2}: {problem.path}')


"""DISCLAIMER:

  This tool was only made to check constraints faster.
  However it is not guaranteed it will find all constraints.
  Checking constraints by yourself is probably the best way.
"""


def check_constraints(problem, settings):
    validate(problem, 'input', settings, check_constraints=True)

    vinput = problem / 'input_validators/input_validator/input_validator.cpp'
    voutput = problem / 'output_validators/output_validator/output_validator.cpp'

    cpp_statement = [
        (re.compile(
            '^(const\s+|constexpr\s+)?(int|string|long long|float|double)\s+(\w+)\s*[=]\s*(.*);'),
         3, 4, None),
        (re.compile(
            '(?:(\w*)\s*=\s*.*)?\.read_(?:string|long_long|int|double|long_double)\((?:\s*([^,]+)\s*,)?\s*([0-9-e.,\']+)\s*[,\)]'
        ), 1, 2, 3),
    ]

    defs_validators = []
    for validator in [vinput, voutput]:
        print(validator)
        if not validator.is_file():
            warn(f'{print_name(validator)} does not exist.')
            continue
        with open(validator) as file:
            for line in file:
                for r, name, v1, v2 in cpp_statement:
                    mo = r.search(line)
                    if mo is not None:
                        if mo.group(v1) is not None:
                            defs_validators.append([mo.group(name) or '', mo.group(v1)])
                        if v2 is not None and mo.group(v2) is not None:
                            defs_validators.append([mo.group(name) or '', mo.group(v2)])

    statement = problem / 'problem_statement/problem.en.tex'
    #latex_define = re.compile('^\\newcommand{\\\\(\w+)}{(.*)}$')
    latex_defines = [
        (re.compile('{\\\\(\w+)}{(.*)}'), 1, 2, False),
        (re.compile('([0-9-e,.^]+)\s*(?:\\\\leq|\\\\geq|\\\\le|\\\\ge|<|>|=)\s*(\w*)'), 2, 1,
         True),
        (re.compile('(\w*)\s*(?:\\\\leq|\\\\geq|\\\\le|\\\\ge|<|>|=)\s*([0-9-e,.^]+)'), 1, 2,
         True),
    ]

    defs_statement = []
    input_output = False
    with open(statement) as file:
        for line in file:
            for r, name, value, io_only in latex_defines:
                if 'begin{Input}' in line:
                    input_output = True
                if 'end{Input}' in line:
                    input_output = False
                if 'begin{Output}' in line:
                    input_output = True
                if 'end{Output}' in line:
                    input_output = False
                if io_only and not input_output:
                    continue

                mo = r.search(line)
                if mo is not None:
                    mo = r.search(line)
                    if mo is not None:
                        if mo.group(value) is not None:
                            defs_statement.append([mo.group(name) or '', mo.group(value)])

    # print all the definitions.
    nl = len(defs_validators)
    nr = len(defs_statement)

    print('{:^30}|{:^30}'.format('  VALIDATORS', '      PROBLEM STATEMENT'), sep='')
    for i in range(0, max(nl, nr)):
        if i < nl:
            print('{:>15}  {:<13}'.format(defs_validators[i][0], defs_validators[i][1]),
                  sep='',
                  end='')
        else:
            print('{:^30}'.format(''), sep='', end='')
        print('|', end='')
        if i < nr:
            print('{:>15}  {:<13}'.format(defs_statement[i][0], defs_statement[i][1]),
                  sep='',
                  end='')
        else:
            print('{:^30}'.format(''), sep='', end='')
        print()

    return True


# Returns the alphanumeric version of a string:
# This reduces it to a string that follows the regex:
# [a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]
def alpha_num(string):
    s = re.sub(r'[^a-zA-Z0-9_.-]', '', string.lower().replace(' ', '-'))
    while s.startswith('_.-'):
        s = s[1:]
    while s.endswith('_.-'):
        s = s[:-1]
    return s


def split_submissions(s):
    # Everything containing data/, .in, or .ans goes into testcases.
    submissions = []
    testcases = []
    for p in s:
        pp = Path(p)
        if 'data/' in p or '.in' in p or '.ans' in p:
            # Strip potential .ans and .in
            if pp.suffix in ['.ans', '.in']:
                testcases.append(pp.with_suffix(''))
            else:
                testcases.append(pp)
        else:
            submissions.append(pp)
    return (submissions, testcases)


def ask_variable(name, default=None):
    if default == None:
        val = ''
        while True:
            print(f"{name}: ", end='')
            val = input()
            if val == '':
                print(f"{name} must not be empty!")
            else:
                break
        return val
    else:
        print(f"{name} [{default}]: ", end='')
        val = input()
        return default if val == '' else val


def new_contest(name):
    # Ask for all required infos.
    title = ask_variable('name', name)
    subtitle = ask_variable('subtitle', '')
    dirname = ask_variable('dirname', alpha_num(title))
    author = ask_variable('author', f'The {title} jury')
    testsession = ask_variable('testsession?', 'n (y/n)')[0] != 'n' # boolean
    year = ask_variable('year', str(datetime.datetime.now().year))
    source = ask_variable('source', title)
    source_url = ask_variable('source url', '')
    license = ask_variable('license', 'cc by-sa')
    rights_owner = ask_variable('rights owner', 'author')

    skeldir = config.tools_root / 'skel/contest'
    util.copytree_and_substitute(skeldir, Path(dirname), locals(), exist_ok=False)


def new_problem():
    problemname = config.args.problemname if config.args.problemname else ask_variable(
        'problem name')
    dirname = ask_variable('dirname', alpha_num(problemname))
    author = config.args.author if config.args.author else ask_variable(
        'author', config.args.author)

    if config.args.custom_validation:
        validation = 'custom'
    elif config.args.default_validation:
        validation = 'default'
    else:
        validation = ask_variable('validation', 'default')

    # Read settings from the contest-level yaml file.
    variables = util.read_yaml(Path('contest.yaml'))

    for k, v in {
            'problemname': problemname,
            'dirname': dirname,
            'author': author,
            'validation': validation
    }.items():
        variables[k] = v

    # Copy tree from the skel directory, next to the contest, if it is found.
    skeldir = config.tools_root / 'skel/problem'
    if Path('skel/problem').is_dir(): skeldir = Path('skel/problem')
    if Path('../skel/problem').is_dir(): skeldir = Path('../skel/problem')
    print(f'Copying {skeldir} to {dirname}.')

    util.copytree_and_substitute(skeldir, Path(dirname), variables, exist_ok=True)

def new_cfp_problem(name):
    shutil.copytree(config.tools_root / 'skel/problem_cfp', name, symlinks=True)


def create_gitlab_jobs(contest, problems):
    def problem_source_dir(problem):
        return problem.resolve().relative_to(Path('..').resolve())

    header_yml = (config.tools_root / 'skel/gitlab-ci-header.yml').read_text()
    print(util.substitute(header_yml, locals()))

    contest_yml = (config.tools_root / 'skel/gitlab-ci-contest.yml').read_text()
    changes = ''
    for problem in problems:
        changes += '      - ' + str(problem_source_dir(problem)) + '/problem_statement/**/*\n'
    print(util.substitute(contest_yml, locals()))

    problem_yml = (config.tools_root / 'skel/gitlab-ci-problem.yml').read_text()
    for problem in problems:
        changesdir = problem_source_dir(problem)
        print('\n')
        print(util.substitute(problem_yml, locals()), end='')


def build_parser():
    parser = argparse.ArgumentParser(description="""
Tools for ICPC style problem sets.
Run this from one of:
    - the repository root, and supply `contest`
    - a contest directory
    - a problem directory
""",
                                     formatter_class=argparse.RawTextHelpFormatter)

    # Global options
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument(
        '-v',
        '--verbose',
        action='count',
        help='Verbose output; once for what\'s going on, twice for all intermediate output.')
    global_parser.add_argument('-c',
                               '--contest',
                               help='The contest to use, when running from repository root.')
    global_parser.add_argument('-p',
                               '--problem',
                               help='The problem to use, when running from repository root.')
    global_parser.add_argument('--no-bar',
                               action='store_true',
                               help='Do not show progress bars in non-interactive environments.')
    global_parser.add_argument('-e',
                               '--error',
                               action='store_true',
                               help='Print full output of failing commands')
    global_parser.add_argument('-E',
                               '--noerror',
                               action='store_true',
                               help='Hide output of failing commands')
    global_parser.add_argument('--cpp_flags',
                               help='Additional compiler flags used for all c++ compilations.')
    global_parser.add_argument(
        '-m',
        '--memory',
        help='The max amount of memory (in bytes) a subprocesses may use. Does not work for java.')
    global_parser.add_argument('--pypy', action='store_true', help='Use pypy instead of cpython.')
    global_parser.add_argument('--force_build',
                               action='store_true',
                               help='Force rebuild instead of only on changed files.')

    subparsers = parser.add_subparsers(title='actions', dest='action')
    subparsers.required = True

    # New contest
    contestparser = subparsers.add_parser('contest',
                                          parents=[global_parser],
                                          help='Add a new contest to the current directory.')
    contestparser.add_argument('contestname', nargs='?', help='The name of the contest')

    # New problem
    problemparser = subparsers.add_parser('problem',
                                          parents=[global_parser],
                                          help='Add a new problem to the current directory.')
    problemparser.add_argument('problemname', nargs='?', help='The name of the problem,')
    problemparser.add_argument('--author', help='The author of the problem,')
    problemparser.add_argument('--custom_validation',
                               action='store_true',
                               help='Use custom validation for this problem.')
    problemparser.add_argument('--default_validation',
                               action='store_true',
                               help='Use default validation for this problem.')

    # New CfP problem
    cfpproblemparser = subparsers.add_parser('cfp_problem', help='Stub for minimal cfp problem.')
    cfpproblemparser.add_argument('shortname',
                                  action='store',
                                  help='The shortname/directory name of the problem.')

    # Problem statements
    pdfparser = subparsers.add_parser('pdf',
                                      parents=[global_parser],
                                      help='Build the problem statement pdf.')
    pdfparser.add_argument('-a',
                           '--all',
                           action='store_true',
                           help='Create problem statements for individual problems as well.')
    pdfparser.add_argument('--web', action='store_true', help='Create a web version of the pdf.')
    pdfparser.add_argument('--cp',
                           action='store_true',
                           help='Copy the output pdf instead of symlinking it.')
    pdfparser.add_argument('--no_timelimit', action='store_true', help='Do not print timelimits.')

    # Solution slides
    solparser = subparsers.add_parser('solutions',
                                      parents=[global_parser],
                                      help='Build the solution slides pdf.')
    solparser.add_argument('-a',
                           '--all',
                           action='store_true',
                           help='Create problem statements for individual problems as well.')
    solparser.add_argument('--cp',
                           action='store_true',
                           help='Copy the output pdf instead of symlinking it.')
    solparser.add_argument('--order',
                           action='store',
                           help='The order of the problems, e.g.: "CAB"')
    solparser.add_argument('--web', action='store_true', help='Create a web version of the pdf.')

    # Validation
    validate_parser = subparsers.add_parser('validate',
                                            parents=[global_parser],
                                            help='validate all grammar')
    validate_parser.add_argument('testcases', nargs='*', help='The testcases to run on.')
    validate_parser.add_argument('--remove', action='store_true', help='Remove failing testcsaes.')
    validate_parser.add_argument('--move_to', help='Move failing testcases to this directory.')
    input_parser = subparsers.add_parser('input',
                                         parents=[global_parser],
                                         help='validate input grammar')
    input_parser.add_argument('testcases', nargs='*', help='The testcases to run on.')
    output_parser = subparsers.add_parser('output',
                                          parents=[global_parser],
                                          help='validate output grammar')
    output_parser.add_argument('testcases', nargs='*', help='The testcases to run on.')

    subparsers.add_parser('constraints',
                          parents=[global_parser],
                          help='prints all the constraints found in problemset and validators')

    # Stats
    subparsers.add_parser('stats',
                          parents=[global_parser],
                          help='show statistics for contest/problem')

    # Generate Testcases
    genparser = subparsers.add_parser('generate',
                                      parents=[global_parser],
                                      help='Generate testcases according to .gen files.')
    genparser.add_argument('-f',
                           '--force',
                           action='store_true',
                           help='Overwrite existing input flies.')
    genparser.add_argument(
        'generators',
        nargs='*',
        help=
        'The generators to run. Everything which has one of these as a prefix will be run. Leading `data/` will be dropped. Empty to generate everything.'
    )

    # Clean
    cleanparser = subparsers.add_parser('clean',
                                        parents=[global_parser],
                                        help='Delete all .in and .ans corresponding to .gen.')

    # Generate Input
    inputgenparser = subparsers.add_parser('generate_random_input',
                                           parents=[global_parser],
                                           help='generate random testcases usinginput validator')
    inputgenparser.add_argument('-f',
                                '--force',
                                action='store_true',
                                help='Overwrite existing input flies.')
    inputgenparser.add_argument('testcases',
                                nargs='+',
                                help='The name of the testcase to generate.')
    inputgenparser.add_argument('--validator',
                                nargs='?',
                                help='The validator to use, in case there is more than one.')
    inputgenparser.add_argument('--retries',
                                default=1,
                                type=int,
                                help='Rerun the generator until it success.')
    inputgenparser.add_argument('--keep',
                                action='store_true',
                                help='Keep output of failed generator runs.')

    # Generate Output
    ansgenparser = subparsers.add_parser('generate_ans',
                                         parents=[global_parser],
                                         help='generate answers testcases')
    ansgenparser.add_argument('-f',
                              '--force',
                              action='store_true',
                              help='Overwrite answers that have changed.')
    ansgenparser.add_argument('submission',
                              nargs='?',
                              help='The program to generate answers. Defaults to first found.')
    ansgenparser.add_argument('-t', '--timelimit', type=int, help='Override the default timeout.')
    ansgenparser.add_argument('--samples',
                              action='store_true',
                              help='Overwrite the samples as well, in combination with -f.')

    # Run
    runparser = subparsers.add_parser('run',
                                      parents=[global_parser],
                                      help='Run multiple programs against some or all input.')
    runparser.add_argument('--table',
                           action='store_true',
                           help='Print a submissions x testcases table for analysis.')
    runparser.add_argument('submissions',
                           nargs='*',
                           help='optionally supply a list of programs and testcases to run')
    runparser.add_argument('-t', '--timeout', type=int, help='Override the default timeout.')
    runparser.add_argument('--timelimit',
                           action='store',
                           type=int,
                           help='Override the default timelimit.')
    runparser.add_argument('--samples', action='store_true', help='Only run on the samples.')

    # Test
    testparser = subparsers.add_parser('test',
                                       parents=[global_parser],
                                       help='Run a single program and print the output.')
    testparser.add_argument('submissions', nargs=1, help='A single submission to run')
    testparser.add_argument('testcases',
                            nargs='*',
                            help='Optionally a list of testcases to run on.')
    testparser.add_argument('--samples', action='store_true', help='Only run on the samples.')
    testparser.add_argument('-t', '--timeout', help='Override the default timeout.')

    # Sort
    subparsers.add_parser('sort',
                          parents=[global_parser],
                          help='sort the problems for a contest by name')

    # All
    allparser = subparsers.add_parser('all',
                                      parents=[global_parser],
                                      help='validate input, validate output, and run programs')
    allparser.add_argument('--cp',
                           action='store_true',
                           help='Copy the output pdf instead of symlinking it.')
    allparser.add_argument('--no_timelimit', action='store_true', help='Do not print timelimits.')

    # Build DomJudge zip
    zipparser = subparsers.add_parser('zip',
                                      parents=[global_parser],
                                      help='Create zip file that can be imported into DomJudge')
    zipparser.add_argument('--skip', action='store_true', help='Skip recreation of problem zips.')
    zipparser.add_argument('-f',
                           '--force',
                           action='store_true',
                           help='Skip validation of input and output files.')
    zipparser.add_argument('--tex',
                           action='store_true',
                           help='Store all relevant files in the problem statement directory.')
    zipparser.add_argument('--kattis',
                           action='store_true',
                           help='Make a zip more following the kattis problemarchive.com format.')
    zipparser.add_argument('--no_solutions', action='store_true', help='Do not compile solutions')

    # Build a zip with all samples.
    subparsers.add_parser('samplezip',
                          parents=[global_parser],
                          help='Create zip file of all samples.')

    # Build a directory for verification with the kattis format
    subparsers.add_parser('kattis',
                          parents=[global_parser],
                          help='Build a directory for verification with the kattis format')

    subparsers.add_parser('gitlabci',
                          parents=[global_parser],
                          help='Print a list of jobs for the given contest.')

    argcomplete.autocomplete(parser)

    return parser


def main():
    # Build Parser
    parser = build_parser()

    # Process arguments
    config.args = parser.parse_args()
    config.verbose = config.args.verbose if hasattr(config.args,
                                                    'verbose') and config.args.verbose else 0
    action = config.args.action

    if action in ['contest']:
        new_contest(config.args.contestname)
        return

    if action in ['problem']:
        new_problem()
        return

    if action in ['cfp_problem']:
        new_cfp_problem(config.args.shortname)
        return

    # Get problem_paths and cd to contest
    # TODO: Migrate from plain problem paths to Problem objects.
    problems, level, contest = get_problems()
    problem_paths = [p.path for p in problems]

    if level != 'problem' and action in [
            'generate', 'generate_random_input', 'generate_ans', 'test'
    ]:
        if action == 'generate':
            fatal('Generating testcases only works for a single problem.')
        if action == 'generate_random_input':
            fatal('Generating random testcases only works for a single problem.')
        if action == 'generate_ans':
            fatal('Generating output files only works for a single problem.')
        if action == 'test':
            fatal('Testing a submission only works for a single problem.')

    if action == 'run':
        if config.args.submissions:
            if level != 'problem':
                fatal('Running a given submission only works from a problem directory.')
            (config.args.submissions, config.args.testcases) = split_submissions(
                config.args.submissions)
        else:
            config.args.testcases = []

    if action in ['stats']:
        stats(problems)
        return

    if action == 'sort':
        print_sorted(problems)
        return

    if action in ['samplezip']:
        export.build_samples_zip(problems)
        return

    if action == 'kattis':
        if level != 'contest':
            print('Only contest level is currently supported...')
            return
        prepare_kattis_directory()
        return

    if action == 'gitlabci':
        create_gitlab_jobs(contest, problem_paths)
        return

    problem_zips = []

    success = True

    for problem in problems:
        if level == 'contest' and action == 'pdf' and not (hasattr(config.args, 'all')
                                                           and config.args.all):
            continue
        print(_c.bold, 'PROBLEM ', problem.path, _c.reset, sep='')

        # merge problem settings with arguments into one namespace
        problemsettings = problem.config
        settings = argparse.Namespace(**problemsettings)
        for key in vars(config.args):
            if vars(config.args)[key] is not None:
                vars(settings)[key] = vars(config.args)[key]

        if action in ['pdf', 'solutions', 'all']:
            # only build the pdf on the problem level, or on the contest level when
            # --all is passed.
            if level == 'problem' or (level == 'contest' and hasattr(config.args, 'all')
                                      and config.args.all):
                success &= latex.build_problem_pdf(problem)

        input_validator_ok = False
        if action in ['validate', 'input', 'all']:
            input_validator_ok = validate(problem.path, 'input', settings)
            success &= input_validator_ok
        if action in ['clean']:
            success &= clean(problem.path)
        if action in ['generate']:
            success &= generate(problem.path, settings)
        if action in ['generate_random_input']:
            success &= generate_random_input(problem.path, settings)
        if action in ['generate_ans']:
            success &= generate_answer(problem.path, settings)
        if action in ['validate', 'output', 'all']:
            success &= validate(problem.path, 'output', settings, input_validator_ok)
        if action in ['run', 'all']:
            success &= run_submissions(problem.path, settings)
        if action in ['test']:
            success &= test_submissions(problem.path, settings)
        if action in ['constraints']:
            success &= check_constraints(problem.path, settings)
        if action in ['zip']:
            # For DJ: export to A.zip
            output = settings.label + '.zip'
            # For Kattis: export to shortname.zip
            if hasattr(config.args, 'kattis') and config.args.kattis:
                output = problem.path.with_suffix('.zip')

            problem_zips.append(output)
            if not config.args.skip:
                success &= latex.build_problem_pdf(problem)
                if not config.args.force:
                    success &= validate(problem.path, 'input', settings)
                    success &= validate(problem.path, 'output', settings, check_constraints=True)

                # Write to problemname.zip, where we strip all non-alphanumeric from the
                # problem directory name.
                success &= export.build_problem_zip(problem.path, output, settings)
        if action == 'kattis':
            export.prepare_kattis_problem(problem.path, settings)

        if len(problems) > 1:
            print()

    if level == 'contest':
        print(f'{_c.bold}CONTEST {contest}{_c.reset}')

        # build pdf for the entire contest
        if action in ['pdf']:
            success &= latex.build_contest_pdf(contest, problems, web=config.args.web)

        if action in ['solutions']:
            success &= latex.build_contest_pdf(contest,
                                               problem_paths,
                                               solutions=True,
                                               web=config.args.web)

        if action in ['zip']:
            success &= latex.build_contest_pdf(contest, problem_paths)
            success &= latex.build_contest_pdf(contest, problem_paths, web=True)
            if not config.args.no_solutions:
                success &= latex.build_contest_pdf(contest, problem_paths, solutions=True)
                success &= latex.build_contest_pdf(contest,
                                                   problem_paths,
                                                   solutions=True,
                                                   web=True)

            outfile = contest + '.zip'
            if config.args.kattis: outfile = contest + '-kattis.zip'
            export.build_contest_zip(problems, problem_zips, outfile, config.args)

    if not success or config.n_error > 0 or config.n_warn > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
