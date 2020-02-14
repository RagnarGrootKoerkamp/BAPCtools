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
import fcntl
import shlex
import stat
import hashlib
import argparse
import argcomplete  # For automatic shell completions
import os
import datetime
import time
import re
import fnmatch
import shutil
import subprocess
import signal
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
from util import ProgressBar, _c, glob, log, warn, error, fatal


# Get the list of relevant problems.
# Either use the problems.yaml, or check the existence of problem.yaml and sort
# by shortname.
def get_problems():
    def is_problem_directory(path):
        # TODO: Simplify this when problem.yaml is required.
        return (path / 'problem.yaml').is_file() or (path / 'problem_statement').is_dir()

    contest = None
    problem = None
    level = None
    if hasattr(config.args, 'contest') and config.args.contest:
        contest = config.args.contest
        os.chdir(contest)
        level = 'problemset'
    elif hasattr(config.args, 'problem') and config.args.problem:
        problem = Path(config.args.problem)
        level = 'problem'
        os.chdir(problem.parent)
    elif is_problem_directory(Path('.')):
        problem = Path().cwd()
        level = 'problem'
        os.chdir('..')
    else:
        level = 'problemset'

    problems = []
    if level == 'problem':
        # TODO: look for a problems.yaml file above here and find a letter?
        problems = [Problem(Path(problem.name))]
    else:
        level = 'problemset'
        # If problemset.yaml is available, use it.
        problemsyaml = Path('problems.yaml')
        if problemsyaml.is_file():
            # TODO: Implement label default value
            problemlist = util.read_yaml(problemsyaml)
            assert problemlist is not None
            labels = dict()
            nextlabel = 'A'
            problems = []
            for p in problemlist:
                label = nextlabel
                if 'label' in p: label = p['label']
                if label == '': fatal(f'Found empty label for problem {p["id"]}')
                nextlabel = label[:-1] + chr(ord(label[-1]) + 1)
                if label in labels: fatal(f'label {label} found twice for problem {p["id"]} and {labels[label]}.')
                labels[label] = p['id']
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

    input_files = list(util.glob(path, '*')) if path.is_dir() else [path]

    # Check file names.
    for f in input_files:
        if not config.COMPILED_FILE_NAME_REGEX.fullmatch(f.name):
            return (None,
                    f'{_c.red}{str(f)} does not match file name regex {config.FILE_NAME_REGEX}')

    linked_files = []
    if len(input_files) == 0:
        config.n_warn += 1
        return (None, f'{_c.red}{str(path)} is an empty directory.{_c.reset}')

    # Link all input files
    last_input_update = 0
    for f in input_files:
        util.ensure_symlink(outdir / f.name, f)
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

    # Get language config
    if config.languages is None:
        # Try both contest and repository level.
        if Path('languages.yaml').is_file():
            config.languages = util.read_yaml(Path('languages.yaml'))
        else:
            config.languages = util.read_yaml(config.tools_root / 'config/languages.yaml')

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
                if 'validators/' in str(f) and f.read_text().find('bits/stdc++.h') != -1:
                    config.n_warn += 1
                    message = f'{_c.orange}{print_name(f)} should not depend on bits/stdc++.h{_c.reset}'

    lang, files, priority = best

    if lang is None:
        return (None, f'{_c.red}No language detected for {path}.{_c.reset}')

    if len(files) == 0:
        return (None, f'{_c.red}No file detected for language {lang} at {path}.{_c.reset}')

    mainfile = None
    if len(files) == 1:
        mainfile = files[0]
    else:
        for f in files:
            if f.ascii_lowercse().starts_with('abcd'):
                mainfile = f
        mainfile = mainfile or sorted(files)[0]

    env = {
        'path': str(outdir),
        # NOTE: This only contains files matching the winning language.
        'files': ''.join(str(f) for f in files),
        'binary': str(runfile),
        'mainfile': str(mainfile),
        'mainclass': str(Path(mainfile).with_suffix('')),
        'Mainclass': str(Path(mainfile).with_suffix('')).capitalize(),
        'memlim': util.get_memory_limit() // 1000000
    }

    # TODO: Support executable files?

    compile_command = config.languages[lang]['compile']
    run_command = config.languages[lang]['run']

    # Prevent building something twice in one invocation of tools.py.
    if compile_command is not None:
        compile_command = shlex.split(compile_command.format(**env))
        ok, err, out = util.exec_command(
            compile_command,
            stdout=subprocess.PIPE,
            memory=5000000000,
            # Compile errors are never cropped.
            crop=False)
        if ok is not True:
            config.n_error += 1
            message = f'{_c.red}FAILED{_c.reset} '
            if err is not None:
                message += '\n' + util.strip_newline(err) + _c.reset
            if out is not None:
                message += '\n' + util.strip_newline(out) + _c.reset
            return (None, message)

    if run_command is not None:
        run_command = shlex.split(run_command.format(**env))

    return (run_command, None)


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

    return build_programs(files)

def validate_testcase(problem, testcase, validators, validator_type, *, bar, check_constraints=False,
        constraints=None):
    ext = '.in' if validator_type == 'input' else '.ans'

    bad_testcase = False
    if validator_type == 'input':
        bad_testcase = 'data/bad/' in str(testcase) and not testcase.with_suffix(
            '.ans').is_file() and not testcase.with_suffix('.out').is_file()

    if validator_type == 'output':
        bad_testcase = 'data/bad/' in str(testcase)

    main_file = testcase.with_suffix(ext)
    if bad_testcase and validator_type == 'output' and main_file.with_suffix('.out').is_file():
        main_file = testcase.with_suffix('.out')

    success = True

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
                validator[1] +
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
                 testcase.with_suffix('.ans'), config.tmpdir] + ['case_sensitive', 'space_change_sensitive'],
                expect=config.RTV_WA if bad_testcase else config.RTV_AC,
                stdin=main_file.open())

        ok = ok is True
        success &= ok
        message = ''

        # Failure?
        if ok:
            message =  'PASSED ' + validator[0]
        else:
            message =  'FAILED ' + validator[0]

        # Print stdout and stderr whenever something is printed
        if not err: err = ''
        if out and config.args.error:
            out = f'\n{_c.red}VALIDATOR STDOUT{_c.reset}\n' + _c.orange + out
        else: out = ''

        bar.part_done(ok, message, data=err+out)

        if not ok:
            # Move testcase to destination directory if specified.
            if hasattr(config.args, 'move_to') and config.args.move_to:
                infile = testcase.with_suffix('.in')
                targetdir = problem / config.args.move_to
                targetdir.mkdir(parents=True, exist_ok=True)
                intarget = targetdir/infile.name
                infile.rename(intarget)
                bar.warn('Moved to ' + print_name(intarget))
                ansfile = testcase.with_suffix('.ans')
                if ansfile.is_file():
                    if validator_type == 'input':
                        ansfile.unlink()
                        bar.warn('Deleted ' + print_name(ansfile))
                    if validator_type == 'output':
                        anstarget = intarget.with_suffix('.ans')
                        ansfile.rename(anstarget)
                        bar.warn('Moved to ' + print_name(anstarget))
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

    return success


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
def validate(problem, validator_type, settings, check_constraints=False):
    assert validator_type in ['input', 'output']

    if check_constraints:
        if not config.args.cpp_flags:
            config.args.cpp_flags = ''
        config.args.cpp_flags += ' -Duse_source_location'

        validators = get_validators(problem, validator_type, check_constraints=True)
    else:
        validators = get_validators(problem, validator_type)

    if settings.validation == 'custom interactive' and validator_type == 'output':
        log('Not validating .ans for interactive problem.')
        return True

    if len(validators) == 0:
        error(f'No {validator_type} validators found!')
        return False

    testcases = util.get_testcases(problem, needans=validator_type == 'output')

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

    success = True

    constraints = {}

    # validate the testcases
    bar = ProgressBar(action, items=[print_name(t)+ext for t in testcases])
    for testcase in testcases:
        bar.start(print_name(testcase.with_suffix(ext)))
        success &= validate_testcase(problem, testcase, validators, validator_type, bar=bar,
                check_constraints=check_constraints, constraints=constraints)
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

    if len(programs) == 0:
        error('No submissions found!')


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


# Return (ret, duration)
def run_testcase(run_command, testcase, outfile, timeout, crop=True):
    with testcase.with_suffix('.in').open('rb') as inf:

        def run(outfile):
            did_timeout = False
            tstart = time.monotonic()
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
            tend = time.monotonic()

            return ok, tend - tstart, err, out

        if outfile is None:
            return run(outfile)
        else:
            return run(outfile.open('wb'))


# return (verdict, time, validator error, submission error)
def process_interactive_testcase(run_command,
                                 testcase,
                                 settings,
                                 output_validators,
                                 validator_error=False,
                                 team_error=False,
                                 *,
                                 # False/None: no output
                                 # True: stdout
                                 # else: path
                                 interaction=False):
    assert len(output_validators) == 1
    output_validator = output_validators[0]

    # Set limits
    validator_timeout = 60

    memory_limit = util.get_memory_limit()
    time_limit, timeout = util.get_time_limits(settings)

    # Validator command
    flags = []
    if settings.space_change_sensitive: flags += ['space_change_sensitive']
    if settings.case_sensitive: flags += ['case_sensitive']
    judgepath = config.tmpdir / 'judge'
    judgepath.mkdir(parents=True, exist_ok=True)
    validator_command = output_validator[1] + [
        testcase.with_suffix('.in'),
        testcase.with_suffix('.ans'), judgepath
    ] + flags

    if validator_error is False: validator_error = subprocess.PIPE
    if team_error is False: team_error = subprocess.PIPE

    # On Windows:
    # - Start the validator
    # - Start the submission
    # - Wait for the submission to complete or timeout
    # - Wait for the validator to complete.
    # This cannot handle cases where the validator reports WA and the submission timeout out
    # afterwards.
    if util.is_windows():

        # Start the validator.
        validator_process = subprocess.Popen(validator_command,
                                             stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE,
                                             stderr=validator_error,
                                             bufsize=2**20)

        # Start and time the submission.
        # TODO: use rusage instead
        tstart = time.monotonic()
        ok, err, out = util.exec_command(run_command,
                                         expect=0,
                                         stdin=validator_process.stdout,
                                         stdout=validator_process.stdin,
                                         stderr=team_error,
                                         timeout=timeout)

        # Wait
        (validator_out, validator_err) = validator_process.communicate()

        tend = time.monotonic()

        did_timeout = tend - tstart > time_limit

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

    # On Linux:
    # - Create 2 pipes
    # - Update the size to 1MB
    # - Start validator
    # - Start submission, limiting CPU time to timelimit+1s
    # - Close unused read end of pipes
    # - Set alarm for timelimit+1s, and kill submission on SIGALRM if needed.
    # - Wait for either validator or submission to finish
    # - Close first program + write end of pipe
    # - Close remaining program + write end of pipe

    def mkpipe():
        # TODO: is os.O_CLOEXEC needed here?
        r, w = os.pipe2(os.O_CLOEXEC)
        F_SETPIPE_SZ = 1031
        fcntl.fcntl(w, F_SETPIPE_SZ, 2**20)
        return r, w

    interaction_file = None
    # TODO: Print interaction when needed.
    if interaction:
        interaction_file = None if interaction is True else interaction.open('a')
        interaction = True

    team_log_in, team_out = mkpipe()
    val_log_in, val_out = mkpipe()
    if interaction:
        val_in, team_log_out = mkpipe()
        team_in, val_log_out = mkpipe()
    else:
        val_in = team_log_in
        team_in = val_log_in

    if interaction:
        # Connect pipes with tee.
        TEE_CODE = R'''
import sys
c = sys.argv[1]
new = True
while True:
    l = sys.stdin.read(1)
    if l=='': break
    sys.stdout.write(l)
    sys.stdout.flush()
    if new: sys.stderr.write(c)
    sys.stderr.write(l)
    sys.stderr.flush()
    new = l=='\n'
'''
        team_tee = subprocess.Popen(['python3', '-c', TEE_CODE, '>'],
                                    stdin=team_log_in,
                                    stdout=team_log_out,
                                    stderr=interaction_file)
        team_tee_pid = team_tee.pid
        val_tee = subprocess.Popen(['python3', '-c', TEE_CODE, '<'],
                                   stdin=val_log_in,
                                   stdout=val_log_out,
                                   stderr=interaction_file)
        val_tee_pid = val_tee.pid

    # Run Validator
    def set_validator_limits():
        resource.setrlimit(resource.RLIMIT_CPU, (validator_timeout, validator_timeout))
        # Increase the max stack size from default to the max available.
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_STACK,
                               (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

    validator = subprocess.Popen(validator_command,
                                 stdin=val_in,
                                 stdout=val_out,
                                 stderr=validator_error,
                                 preexec_fn=set_validator_limits)
    validator_pid = validator.pid

    # Run Submission
    def set_submission_limits():
        resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
        # Increase the max stack size from default to the max available.
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_STACK,
                               (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
        if memory_limit:
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

    submission = subprocess.Popen(run_command,
                                  stdin=team_in,
                                  stdout=team_out,
                                  stderr=team_error,
                                  preexec_fn=set_submission_limits)
    submission_pid = submission.pid

    os.close(team_out)
    os.close(val_out)
    if interaction:
        os.close(team_log_out)
        os.close(val_log_out)

    # To be filled
    validator_status = None
    submission_status = None
    submission_time = None
    first = None

    # Raise alarm after timeout reached
    signal.alarm(timeout)

    def kill_submission(signal, frame):
        submission.kill()
        nonlocal submission_time
        submission_time = timeout

    signal.signal(signal.SIGALRM, kill_submission)

    # Wait for first to finish
    for i in range(4 if interaction else 2):
        pid, status, rusage = os.wait3(0)
        status >>= 8

        if pid == validator_pid:
            if first is None: first = 'validator'
            validator_status = status
            # Kill the team submission in case we already know it's WA.
            if i == 0 and validator_status != config.RTV_AC:
                submission.kill()
            continue

        if pid == submission_pid:
            signal.alarm(0)
            if first is None: first = 'submission'
            submission_status = status
            # Possibly already written by the alarm.
            if not submission_time:
                submission_time = rusage.ru_utime + rusage.ru_stime
            continue

        if pid == team_tee_pid: continue
        if pid == val_tee_pid: continue

        assert False

    os.close(team_in)
    os.close(val_in)
    if interaction:
        os.close(team_log_in)
        os.close(val_log_in)

    did_timeout = submission_time > time_limit

    # If team exists first with TLE/RTE -> TLE/RTE
    # If team exists first nicely -> validator result
    # If validator exits first with WA -> WA
    # If validator exits first with AC:
    # - team TLE/RTE -> TLE/RTE
    # - more team output -> WA
    # - no more team output -> AC

    if validator_status != config.RTV_AC and validator_status != config.RTV_WA:
        config.n_error += 1
        verdict = 'VALIDATOR_CRASH'
    elif first == 'validator':
        # WA has priority because validator reported it first.
        if validator_status == config.RTV_WA:
            verdict = 'WRONG_ANSWER'
        elif submission_status != 0:
            verdict = 'RUN_TIME_ERROR'
        elif did_timeout:
            verdict = 'TIME_LIMIT_EXCEEDED'
        else:
            verdict = 'ACCEPTED'
    else:
        assert first == 'submission'
        if submission_status != 0:
            verdict = 'RUN_TIME_ERROR'
        elif did_timeout:
            verdict = 'TIME_LIMIT_EXCEEDED'
        elif validator_status == config.RTV_WA:
            verdict = 'WRONG_ANSWER'
        else:
            verdict = 'ACCEPTED'

    val_err = None
    if validator_error is not None: val_err = validator.stderr.read().decode('utf-8')
    team_err = None
    if team_error is not None: team_err = submission.stderr.read().decode('utf-8')
    return (verdict, submission_time, val_err, team_err)


# return (verdict, time, remark)
def process_testcase(run_command,
                     testcase,
                     outfile,
                     settings,
                     output_validators):

    if 'interactive' in settings.validation:
        return process_interactive_testcase(run_command, testcase, settings, output_validators)

    timelimit, timeout = util.get_time_limits(settings)
    ok, duration, err, out = run_testcase(run_command, testcase, outfile, timeout)
    did_timeout = duration > timelimit
    verdict = None
    if did_timeout:
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
                                                      output_validators)

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
            if 'interactive' in settings.validation: output_type = 'PROGRAM STDERR'
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
    if 'interactive' in settings.validation: needans = False
    testcases = util.get_testcases(problem, needans=needans)

    if len(testcases) == 0:
        return False

    output_validators = None
    if settings.validation in ['custom', 'custom interactive']:
        output_validators = get_validators(problem, 'output')
        if len(output_validators) == 0:
            error(f'No output validators found, but validation type is: {settings.validation}.')
            return False

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


def test_submission(problem, submission, testcases, settings):
    print(ProgressBar.action('Running', str(submission[0])))

    if 'interactive' in settings.validation:
        output_validators = get_validators(problem, 'output')
        if len(output_validators) != 1:
            error(
                'Interactive problems need exactly one output validator. Found {len(output_validators)}.'
            )
            return False

    time_limit, timeout = util.get_time_limits(settings)
    for testcase in testcases:
        header = ProgressBar.action('Running ' + str(submission[0]), str(testcase.with_suffix('')))
        print(header)

        if 'interactive' not in settings.validation:
            # err and out should be None because they go to the terminal.
            ok, duration, err, out = run_testcase(submission[1],
                                                  testcase,
                                                  outfile=None,
                                                  timeout=timeout,
                                                  crop=False)
            did_timeout = duration > time_limit
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

        else:
            # Interactive problem.
            verdict, duration, val_err, team_err = process_interactive_testcase(
                submission[1],
                testcase,
                settings,
                output_validators,
                interaction=True,
                validator_error=None,
                team_error=None)
            if verdict != 'ACCEPTED':
                config.n_error += 1
                print(f'{_c.red}{verdict}{_c.reset} {_c.bold}{duration:6.3f}s{_c.reset}')
            else:
                print(f'{_c.green}{verdict}{_c.reset} {_c.bold}{duration:6.3f}s{_c.reset}')


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
            test_submission(problem, submission, testcases, settings)
    return True


# Return config, generator_runs pair
def parse_gen_yaml(problem):
    yaml_path = problem / 'generators' / 'gen.yaml'
    if not yaml_path.is_file():
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

    generate_ans = settings.validation != 'custom interactive'
    submission = None
    retries = 1
    if gen_config:
        if 'generate_ans' in gen_config:
            generate_ans = gen_config['generate_ans']
        if generate_ans and 'submission' in gen_config and gen_config['submission']:
            submission = problem / gen_config['submission']
        if 'retries' in gen_config:
            retries = max(gen_config['retries'], 1)

    if generate_ans and submission is None:
        # Use one of the accepted submissions.
        submissions = list(glob(problem, 'submissions/accepted/*'))
        if len(submissions) == 0:
            warn('No submissions found!')
        else:
            submissions.sort()
            # Look for a c++ solution if available.
            for s in submissions:
                if s.suffix == '.cpp':
                    submission = s
                    break
                else:
                    if submission is None:
                        submission = s
        if submission is not None:
            log(f'No submission was specified in generators/gen.yaml. Falling back to {submission}.')

    if generate_ans and submission is not None:
        if not (submission.is_file() or submission.is_dir()):
            error(f'Submission not found: {submission}')
            submission = None
        else:
            bar = ProgressBar('Building', items=[print_name(submission)])
            bar.start(print_name(submission))
            submission, msg = build(submission)
            bar.done(submission is not None, msg)
    if submission is None: generate_ans = False

    input_validators  = get_validators(problem, 'input' ) if len(generator_runs) > 0 else []
    output_validators = get_validators(problem, 'output') if generate_ans else []

    if len(generator_runs) == 0 and generate_ans is False:
        return True

    nskip = 0
    nfail = 0

    timeout = util.get_timeout()

    # Move source to target but check that --force was passed if target already exists and source is
    # different. Overwriting samples needs --samples as well.
    def maybe_move(source, target, tries_msg=''):
        nonlocal nskip

        # Validate new .in and .ans files
        if source.suffix == '.in':
            if not validate_testcase(problem, source, input_validators, 'input', bar=bar):
                return False
        if source.suffix == '.ans' and settings.validation is not 'custom interactive':
            if not validate_testcase(problem, source, output_validators, 'output', bar=bar):
                return False

        # Ask -f or -f --samples before overwriting files.
        if target.is_file():
            if source.read_text() == target.read_text():
                return True

            if 'sample' in str(target) and (not (hasattr(settings, 'samples') and settings.samples)
                    or not (hasattr(settings, 'force') and settings.force)):
                bar.warn('SKIPPED: ' + target.name + _c.reset +
                         '; supply -f --samples to overwrite')
                return False

            if not (hasattr(settings, 'force') and settings.force):
                nskip += 1
                bar.warn('SKIPPED: ' + target.name + _c.reset + '; supply -f to overwrite')
                return False

        if target.is_file():
            bar.log('CHANGED: ' + target.name + tries_msg)
        else:
            bar.log('NEW: ' + target.name + tries_msg)
        shutil.move(source, target)
        return False


    tmpdir = config.tmpdir / problem.name / 'generate'
    tmpdir.mkdir(parents=True, exist_ok=True)

    # Generate Input
    if len(generator_runs) > 0:
        bar = ProgressBar('Generate', items=generator_runs)

        for file_name in generator_runs:
            commands = generator_runs[file_name]

            bar.start(str(file_name))

            (problem / 'data' / file_name.parent).mkdir(parents=True, exist_ok=True)

            stdin_path = tmpdir / file_name.name
            stdout_path = tmpdir / (file_name.name + '.stdout')

            # Try running all commands |retries| times.
            ok = True
            for retry in range(retries):
                # Clean the directory.
                for f in tmpdir.iterdir():
                    f.unlink()

                for command in commands:
                    input_command = shlex.split(command)

                    generator_name = input_command[0]
                    input_args = input_command[1:]

                    for i in range(len(input_args)):
                        x = input_args[i]
                        if x == '$SEED':
                            val = int(hashlib.sha512(command.encode('utf-8')).hexdigest(),
                                      16) % (2**31)
                            input_args[i] = (val + retry) % (2**31)

                    generator_command, msg = build(problem / 'generators' / generator_name)
                    if generator_command is None:
                        bar.error(msg)
                        ok = False
                        break

                    command = generator_command + input_args

                    stdout_file = stdout_path.open('w')
                    stdin_file = stdin_path.open('r') if stdin_path.is_file() else None
                    try_ok, err, out = util.exec_command(command,
                                                         stdout=stdout_file,
                                                         stdin=stdin_file,
                                                         timeout=timeout,
                                                         cwd=tmpdir)
                    stdout_file.close()
                    if stdin_file: stdin_file.close()

                    if stdout_path.is_file():
                        shutil.move(stdout_path, stdin_path)

                    if try_ok == -9:
                        # Timeout
                        bar.error(f'TIMEOUT after {timeout}s')
                        nfail += 1
                        ok = False
                        break

                    if try_ok is not True:
                        nfail += 1
                        try_ok = False
                        break

                if not ok: break
                if try_ok: break

            if not try_ok:
                bar.error('FAILED: ' + err)
                ok = False

            tries_msg = '' if retry == 0 else f' after {retry+1} tries'

            # Copy all generated files back to the data directory.
            if ok:
                for f in tmpdir.iterdir():
                    if f.stat().st_size == 0: continue

                    target = problem / 'data' / file_name.parent / f.name
                    ok &= maybe_move(f, target, tries_msg)

            bar.done(ok)

        if not config.verbose and nskip == 0 and nfail == 0:
            print(ProgressBar.action('Generate', f'{_c.green}Done{_c.reset}'))

    if generate_ans is False or submission is None:
        return nskip == 0 and nfail == 0

    # Generate Answer
    _, timeout = util.get_time_limits(settings)

    if settings.validation != 'custom interactive':
        testcases = util.get_testcases(problem, needans=False)
        bar = ProgressBar('Generate ans', items=[print_name(t.with_suffix('.ans')) for t in testcases])

        for testcase in testcases:
            bar.start(print_name(testcase.with_suffix('.ans')))

            outfile = tmpdir / testcase.with_suffix('.ans').name
            try:
                outfile.unlink()
            except OSError:
                pass

            # Ignore stdout and stderr from the program.
            ok, duration, err, out = run_testcase(submission, testcase, outfile, timeout)
            if ok is not True or duration > timeout:
                if duration > timeout:
                    bar.error('TIMEOUT')
                    nfail += 1
                else:
                    bar.error('FAILED')
                    nfail += 1
            else:
                util.ensure_symlink(outfile.with_suffix('.in'), testcase)
                ok &= maybe_move(outfile, testcase.with_suffix('.ans'))

            bar.done(ok)

        if not config.verbose and nskip == 0 and nfail == 0:
            print(ProgressBar.action('Generate ans', f'{_c.green}Done{_c.reset}'))

    else:
        # For interactive problems:
        # - create empty .ans files
        # - create .interaction files for samples only
        testcases = util.get_testcases(problem, needans=False, only_sample=True)
        bar = ProgressBar('Generate interaction', items=[print_name(t.with_suffix('.interaction')) for t in testcases])

        for testcase in testcases:
            bar.start(print_name(testcase.with_suffix('.interaction')))

            outfile = tmpdir / testcase.with_suffix('.interaction').name
            try:
                outfile.unlink()
            except OSError:
                pass

            # Ignore stdout and stderr from the program.
            verdict, duration, err, out = process_interactive_testcase(submission,
                    testcase, settings, output_validators,
                    validator_error=None,
                    team_error=None,
                    interaction=outfile
                    )
            if verdict != 'ACCEPTED':
                if duration > timeout:
                    bar.error('TIMEOUT')
                    nfail += 1
                else:
                    bar.error('FAILED')
                    nfail += 1
            else:
                ok &= maybe_move(outfile, testcase.with_suffix('.interaction'))

            bar.done(ok)

        if not config.verbose and nskip == 0 and nfail == 0:
            print(ProgressBar.action('Generate ans', f'{_c.green}Done{_c.reset}'))


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
    s = re.sub(r'[^a-zA-Z0-9_.-]', '', string.lower().replace(' ', '').replace('-', ''))
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
    testsession = ask_variable('testsession?', 'n (y/n)')[0] != 'n'  # boolean
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

    for k in ['source', 'source_url', 'license', 'rights_owner']:
        if k not in variables: variables[k] = ''

    # Copy tree from the skel directory, next to the contest, if it is found.
    skeldir = config.tools_root / 'skel/problem'
    if Path('skel/problem').is_dir(): skeldir = Path('skel/problem')
    if Path('../skel/problem').is_dir(): skeldir = Path('../skel/problem')
    if config.args.skel: skeldir = Path(config.args.skel)
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
                               '--problemset',
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
    global_parser.add_argument('--force_build',
                               action='store_true',
                               help='Force rebuild instead of only on changed files.')

    subparsers = parser.add_subparsers(title='actions', dest='action')
    subparsers.required = True

    # New contest
    contestparser = subparsers.add_parser('new_contest',
                                          parents=[global_parser],
                                          help='Add a new contest to the current directory.')
    contestparser.add_argument('contestname', nargs='?', help='The name of the contest')

    # New problem
    problemparser = subparsers.add_parser('new_problem',
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
    problemparser.add_argument('--skel', help='Skeleton problem directory to copy from.')

    # New CfP problem
    cfpproblemparser = subparsers.add_parser('new_cfp_problem',
                                             help='Stub for minimal cfp problem.')
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
    genparser.add_argument('-t', '--timeout', type=int, help='Override the default timeout.')
    genparser.add_argument('--samples',
                           action='store_true',
                           help='Overwrite the samples as well, in combination with -f.')

    # Clean
    cleanparser = subparsers.add_parser('clean',
                                        parents=[global_parser],
                                        help='Delete all .in and .ans corresponding to .gen.')

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
    runparser.add_argument('--timelimit', type=int, help='Override the default timelimit.')
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

    if action in ['new_contest']:
        new_contest(config.args.contestname)
        return

    if action in ['new_problem']:
        new_problem()
        return

    if action in ['new_cfp_problem']:
        new_cfp_problem(config.args.shortname)
        return

    # Get problem_paths and cd to contest
    # TODO: Migrate from plain problem paths to Problem objects.
    problems, level, contest = get_problems()
    problem_paths = [p.path for p in problems]

    if level != 'problem' and action in ['generate', 'test']:
        if action == 'generate':
            fatal('Generating testcases only works for a single problem.')
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
        if level != 'new_contest':
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
        if level == 'problemset' and action == 'pdf' and not (hasattr(config.args, 'all')
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
            if level == 'problem' or (level == 'problemset' and hasattr(config.args, 'all')
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
            output = problem.label + '.zip'
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

    if level == 'problemset':
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
