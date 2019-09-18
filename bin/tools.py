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
import time
import yaml
import configparser
import io
import zipfile
from pathlib import Path

# Local imports
import config
import export
import latex
import util
import validation
from util import ProgressBar, _c, glob


# Get the list of relevant problems.
# Either use the provided contest, or check the existence of problem.yaml.
# Returns problems in sorted order by probid in domjudge.ini.
def get_problems():

  def is_problem_directory(path):
    return (path / 'problem.yaml').is_file() or (path /
                                                 'problem_statement').is_dir()

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
    problems = [Path(problem.name)]
  else:
    level = 'contest'
    dirs = [p[0] for p in util.sort_problems(glob(Path('.'), '*/'))]
    for problem in dirs:
      if is_problem_directory(problem):
        problems.append(problem)

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
  return path.is_file() and (path.stat().st_mode &
                             (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH))


# Look at the shebang at the first line of the file to choose between python 2
# and python 3.
def python_version(path):
  shebang = path.read_text().split('\n')[0]
  if re.match('^#!.*python2', shebang):
    return 'python2'
  if re.match('^#!.*python3', shebang):
    return 'python3'
  return 'python2'


def python_interpreter(version):
  if hasattr(config.args, 'pypy') and config.args.pypy:
    if version == 'python2':
      return 'pypy'
    #print('\n' + _c.orange + 'Pypy only works for python2! Using cpython for python3.' + _c.reset)
  return version


# A function to convert c++ or java to something executable.
# Returns a command to execute and an optional error message.
# This can take either a path to a file (c, c++, java, python) or a directory.
# The directory may contain multiple files.
def build(path):
  # mirror directory structure on tmpfs
  if path.is_absolute():
    outdir = config.tmpdir / path.name
  else:
    outdir = config.tmpdir / path
    if not str(outdir.resolve()).startswith(str(config.tmpdir)):
      outdir = config.tmpdir / path.name

  outdir.mkdir(parents=True, exist_ok=True)
  for f in outdir.glob('*'):
    f.unlink()
  outfile = outdir / 'run'

  # Link all input files
  files = list(path.glob('*')) if path.is_dir() else [path]
  if len(files) == 0:
    config.n_warn += 1
    return (None, f'{_c.red}{str(path)} is an empty directory.{_c.reset}')
  for f in files:
    latex.ensure_symlink(outdir / f.name, f)

  # If build or run present, use them:
  if is_executable(outdir / 'build'):
    cur_path = os.getcwd()
    os.chdir(outdir)
    if util.exec_command(['./build'], memory=5000000000)[0] is not True:
      config.n_error += 1
      return (None, f'{_c.red}FAILED{_c.reset}')
    os.chdir(cur_path)
    if not is_executable(outdir / 'run'):
      config.n_error += 1
      return (None, f'{_c.red}FAILED{_c.reset}: {runfile} must be executable')

  if is_executable(outdir / 'run'):
    return ([outdir / 'run'], None)

  # Otherwise, detect the language and entry point and build manually.
  language_code = None
  main_file = None if path.is_dir() else outdir / path.name
  c_files = []
  for f in files:
    e = f.suffix

    lang = None
    main = False

    if e in ['.c']:
      lang = 'c'
      main = True
      c_files.append(outdir / f.name)
    if e in ['.cc', '.cpp', '.cxx.', '.c++', '.C']:
      lang = 'cpp'
      main = True
      c_files.append(outdir / f.name)
    if e in ['.java']:
      lang = 'java'
      main = f.name == 'Main.java'
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

  if language_code is None:
    config.n_error += 1
    return (None, f'{_c.red}No language detected for {path}.{_c.reset}')

  compile_command = None
  run_command = None

  if language_code == 'c':
    compile_command = [
        'gcc', '-I', config.tools_root / 'headers', '-std=c11', '-Wall', '-O2',
        '-o', outfile
    ] + c_files + ['-lm']
    run_command = [outfile]
  elif language_code == 'cpp':
    compile_command = ([
        '/usr/bin/g++',
        '-I',
        config.tools_root / 'headers',
        '-std=c++14',
        '-Wall',
        '-O2',
        '-fdiagnostics-color=always',  # Enable color output
        '-o',
        outfile,
        main_file
    ] + ([] if config.args.cpp_flags is None else config.args.cpp_flags.split())
                      )
    run_command = [outfile]
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
  elif language_code in ['python2', 'python3']:
    run_command = [python_interpreter(language_code), main_file]
  elif language_code == 'ctd':
    ctd_path = config.tools_root / 'checktestdata' / 'checktestdata'
    if ctd_path.is_file():
      run_command = [ctd_path, main_file]
  else:
    config.n_error += 1
    return (None,
            f'{_c.red}Unknown extension \'{ext}\' at file {path}{_c.reset}')

  # Prevent building something twice in one invocation of tools.py.
  message = ''
  if compile_command is not None:  # and not outfile.is_file():
    ok, err, out = util.exec_command(
        compile_command, stdout=subprocess.PIPE, memory=5000000000)
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
    else:
      bar.log(message)
    bar.done()
  if config.verbose:
    print()
  return commands


# Drops the first two path components <problem>/<type>/
def print_name(path):
  return str(Path(*path.parts[2:]))


def get_validators(problem, validator_type):
  files = (
      glob(problem / (validator_type + '_validators'), '*') +
      glob(problem / (validator_type + '_format_validators'), '*'))

  validators = build_programs(files)

  if len(validators) == 0:
    config.n_error += 1
    print(
        f'\n{_c.red}Aborting: At least one {validator_type} validator is needed!{_c.reset}'
    )

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
def validate(problem,
             validator_type,
             settings,
             printnewline=False,
             check_constraints=False):
  assert validator_type in ['input', 'output']

  if validator_type == 'output' and settings.validation == 'custom':
    return True

  validators = get_validators(problem, validator_type)
  if len(validators) == 0:
    return False

  testcases = util.get_testcases(problem, validator_type == 'output')
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
  max_testcase_len = max(
      [len(print_name(testcase) + ext) for testcase in testcases])

  constraints = {}

  # validate the testcases
  bar = ProgressBar(action, max_testcase_len, len(testcases))
  for testcase in testcases:
    bar.start(print_name(testcase.with_suffix(ext)))
    for validator in validators:
      # simple `program < test.in` for input validation and ctd output validation
      if Path(validator[0]).suffix == '.ctd':
        ok, err, out = util.exec_command(
            validator[1] + flags,
            expect=config.RTV_AC,
            stdin=testcase.with_suffix(ext).open())
      elif validator_type == 'input':
        constraints_file = config.tmpdir / 'constraints'
        if constraints_file.is_file():
          constraints_file.unlink()
        ok, err, out = util.exec_command(
            # TODO: Store constraints per problem.
            validator[1] + flags + (['--constraints_file', constraints_file]
                                    if check_constraints else []),
            expect=config.RTV_AC,
            stdin=testcase.with_suffix(ext).open())

        # Merge with previous constraints.
        if constraints_file.is_file():
          for line in constraints_file.read_text().splitlines():
            loc, has_low, has_high, vmin, vmax, low, high = line.split()
            has_low = bool(int(has_low))
            has_high = bool(int(has_high))
            vmin = int(vmin)
            vmax = int(vmax)
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
            validator[1] + [
                testcase.with_suffix('.in'),
                testcase.with_suffix('.ans'), config.tmpdir
            ] + flags,
            expect=config.RTV_AC,
            stdin=testcase.with_suffix(ext).open())

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

      # Print stderr whenever something is printed
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
          ProgressBar.clearline()
          printnewline = False
          print()
        bar.log(message)
    bar.done()

  # Make sure all constraints are satisfied.
  for loc, value in constraints.items():
    loc = Path(loc).name
    has_low, has_high, vmin, vmax, low, high = value
    if not has_low:
      print(
          f'{_c.orange}BOUND NOT REACHED: The value at {loc} was never equal to the lower bound of {low}. Min value found: {vmin}{_c.reset}'
      )
    if not has_high:
      print(
          f'{_c.orange}BOUND NOT REACHED: The value at {loc} was never equal to the upper bound of {high}. Max value found: {vmax}{_c.reset}'
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
      ('   Ival', ['input_validators/*']),
      ('Oval', ['output_validators/*']),
      ('   sample', 'data/sample/*.in', 2),
      ('secret', 'data/secret/*.in', 15, 50),
      ('   AC', 'submissions/accepted/*', 3),
      (' WA', 'submissions/wrong_answer/*', 2),
      ('TLE', 'submissions/time_limit_exceeded/*', 1),
      ('   cpp', 'submissions/accepted/*.c*', 1),
      ('java', 'submissions/accepted/*.java', 1),
      ('py2', ['submissions/accepted/*.py', 'submissions/accepted/*.py2'], 1),
      ('py3', 'submissions/accepted/*.py3', 1),
  ]

  headers = ['problem'] + [h[0] for h in stats]
  cumulative = [0] * len(stats)

  header_string = ''
  format_string = ''
  for header in headers:
    if header == 'problem':
      width = len(header)
      for problem in problems:
        width = max(width, len(problem.name))
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
      for p in glob(problem, path):
        # Exclude files containing 'TODO: Remove'.
        if p.is_file():
          with p.open() as file:
            data = file.read()
            if data.find('TODO: Remove') == -1:
              cnt += 1
        if p.is_dir():
          cnt += 1
      return cnt

    counts = [count(s[1]) for s in stats]
    for i in range(0, len(stats)):
      cumulative[i] = cumulative[i] + counts[i]
    print(
        format_string.format(
            problem.name, *[
                get_stat(counts[i], True if len(stats[i]) <= 2 else stats[i][2],
                         None if len(stats[i]) <= 3 else stats[i][3])
                for i in range(len(stats))
            ]))

  # print the cumulative count
  print('-' * len(header))
  print(
      format_string.format(*(
          ['TOTAL'] + list(map(lambda x: get_stat(x, False), cumulative)))))


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
          ok, err, out = util.exec_command(
              run_command,
              expect=0,
              crop=crop,
              stdin=inf,
              stdout=None,
              stderr=None,
              timeout=timeout)
        else:
          ok, err, out = util.exec_command(
              run_command,
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
      with open(outfile, 'wb') as outf:
        return run(outf)


# return (verdict, time, remark)
def process_testcase(run_command,
                     testcase,
                     outfile,
                     settings,
                     output_validators,
                     printnewline=False):

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
      ok, err, out = validation.default_output_validator(
          testcase.with_suffix('.ans'), outfile, settings)
    elif settings.validation == 'custom':
      ok, err, out = validation.custom_output_validator(testcase, outfile,
                                                        settings,
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

  verdict_count = {}
  for outcome in config.PROBLEM_OUTCOMES:
    verdict_count[outcome] = 0
  time_total = 0
  time_max = 0

  action = 'Running ' + str(submission[0])
  max_total_length = max(
      max([len(print_name(testcase.with_suffix(''))) for testcase in testcases
          ]), 15) + max_submission_len
  max_testcase_len = max_total_length - len(str(submission[0]))

  printed = False
  bar = ProgressBar(action, max_testcase_len, len(testcases))

  for testcase in testcases:
    bar.start(print_name(testcase.with_suffix('')))
    outfile = config.tmpdir / 'test.out'
    verdict, runtime, err, out = process_testcase(submission[1], testcase,
                                                  outfile, settings,
                                                  output_validators,
                                                  need_newline)
    if verdict != 'VALIDATOR_CRASH':
      verdict_count[verdict] += 1

    time_total += runtime
    time_max = max(time_max, runtime)

    if table_dict is not None:
      table_dict[testcase] = verdict == 'ACCEPTED'

    got_expected = verdict == 'ACCEPTED' or verdict == expected
    color = _c.green if got_expected else _c.red
    print_message = config.verbose > 0 or not got_expected
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
      message += f'\n{_c.red}STDOUT{_c.reset}' + prefix + _c.orange + util.strip_newline(
          out) + _c.reset

    if print_message:
      bar.log(message)
      printed = True

    bar.done()

    if not config.verbose and verdict in [
        'TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR'
    ]:
      break

  verdict = 'ACCEPTED'
  for v in reversed(config.PROBLEM_OUTCOMES):
    if verdict_count[v] > 0:
      verdict = v
      break

  # Use a bold summary line if things were printed before.
  if printed:
    color = _c.boldgreen if verdict == expected else _c.boldred
  else:
    color = _c.green if verdict == expected else _c.red

  time_avg = time_total / len(testcases)

  # Print summary line
  boldcolor = _c.bold if printed else ''
  print(
      f'{action:<{max_total_length-6}} {boldcolor}max/avg {time_max:6.3f}s {time_avg:6.3f}s {color}{verdict}{_c.reset}'
  )

  if printed:
    print()

  return verdict == expected


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
  testcases = util.get_testcases(problem, needans=True)

  if len(testcases) == 0:
    print(_c.red + 'No testcases found!' + _c.reset)
    return False

  output_validators = None
  if settings.validation == 'custom':
    output_validators = get_validators(problem, 'output')
    if len(output_validators) == 0:
      return False

  #if hasattr(config.args, 'timelimit') and config.args.timelimit is not None:
  #settings.timelimit = float(config.args.timelimit)

  submissions = get_submissions(problem)

  max_submission_len = max(
      [0] + [len(str(x[0])) for cat in submissions for x in submissions[cat]])

  success = True
  verdict_table = []
  for verdict in submissions:
    for submission in submissions[verdict]:
      verdict_table.append(dict())
      success &= run_submission(
          submission,
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

    make_verdict = lambda tc: ''.join(
        map(lambda row: single_verdict(row, testcase), verdict_table))
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
    header = ProgressBar.action('Running ' + str(submission[0]),
                                str(testcase.with_suffix('')))
    print(header)
    outfile = config.tmpdir / 'test.out'
    # err and out should be None because they go to the terminal.
    ok, did_timeout, duration, err, out = run_testcase(
        submission[1], testcase, outfile=None, tle=timeout, crop=False)
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
    print(_c.red + 'No testcases found!' + _c.reset)
    return False

  submissions = get_submissions(problem)

  verdict_table = []
  for verdict in submissions:
    for submission in submissions[verdict]:
      test_submission(submission, testcases, settings)
  return True


def generate_output(problem, settings):
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
      os.unlink(outfile)
    except OSError:
      pass

    # Ignore stdout and stderr from the program.
    ok, timeout, duration, err, out = run_testcase(run_command, testcase,
                                                   outfile, settings.timelimit)
    message = ''
    same = False
    if ok is not True or timeout is True:
      message = 'FAILED'
      nfail += 1
    else:
      if os.access(testcase.with_suffix('.ans'), os.R_OK):
        compare_settings = argparse.Namespace()
        compare_settings.__dict__.update({
            'case_sensitive': True,
            'space_change_sensitive': True,
            'floatabs': None,
            'floatrel': None
        })
        if validation.default_output_validator(
            testcase.with_suffix('.ans'), outfile, compare_settings)[0]:
          same = True
          nsame += 1
        else:
          if hasattr(settings, 'force') and settings.force:
            shutil.move(outfile, testcase.with_suffix('.ans'))
            nchange += 1
            message = 'CHANGED'
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
  for problem in util.sort_problems(problems):
    print(prefix + problem[0])


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
          '^(const\s+|constexpr\s+)?(int|string|long long|float|double)\s+(\w+)\s*[=]\s*(.*);'
      ), 3, 4, None),
      (re.compile(
          '(?:(\w*)\s*=\s*.*)?\.read_(?:string|long_long|int|double|long_double)\((?:\s*([^,]+)\s*,)?\s*([0-9-e.,\']+)\s*[,\)]'
      ), 1, 2, 3),
  ]

  defs_validators = []
  for validator in [vinput, voutput]:
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
      (re.compile(
          '([0-9-e,.^]+)\s*(?:\\\\leq|\\\\geq|\\\\le|\\\\ge|<|>|=)\s*(\w*)'), 2,
       1, True),
      (re.compile(
          '(\w*)\s*(?:\\\\leq|\\\\geq|\\\\le|\\\\ge|<|>|=)\s*([0-9-e,.^]+)'), 1,
       2, True),
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

  print(
      '{:^30}|{:^30}'.format('  VALIDATORS', '      PROBLEM STATEMENT'), sep='')
  for i in range(0, max(nl, nr)):
    if i < nl:
      print(
          '{:>15}  {:<13}'.format(defs_validators[i][0], defs_validators[i][1]),
          sep='',
          end='')
    else:
      print('{:^30}'.format(''), sep='', end='')
    print('|', end='')
    if i < nr:
      print(
          '{:>15}  {:<13}'.format(defs_statement[i][0], defs_statement[i][1]),
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
    if 'data/' in p or '.in' in p or '.ans' in p:
      # Strip potential .ans and .in
      (base, ext) = os.path.splitext(p)
      if ext in ['.ans', '.in']:
        testcases.append(base)
      else:
        testcases.append(p)
    else:
      submissions.append(p)
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
  testsession = ('% ' if ask_variable('testsession?', 'n (y/n)')[0] == 'n' else
                 '') + '\\testsession'
  year = ask_variable('year', str(datetime.datetime.now().year))
  source = ask_variable('source', title)
  source_url = ask_variable('source url', '')
  license = ask_variable('license', 'cc by-sa')
  rights_owner = ask_variable('rights owner', 'author')

  shutil.copytree(config.tools_root / 'skel/contest', dirname, symlinks=True)

  util.substitute_dir_variables(Path(dirname), locals())


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
  variables = {
      'problemname': problemname,
      'dirname': dirname,
      'author': author,
      'validation': validation
  }
  for k, v in util.read_yaml(Path('contest.yaml')).items():
    variables[k] = v

  for key in variables:
    print(key, ' -> ', variables[key])

  shutil.copytree(config.tools_root / 'skel/problem', dirname, symlinks=True)

  util.substitute_dir_variables(Path(dirname), variables)


def create_gitlab_jobs(contest, problems):

  def problem_source_dir(problem):
    return problem.resolve().relative_to(Path('..').resolve())

  header_yml = (config.tools_root / 'skel/gitlab-ci-header.yml').read_text()
  print(util.substitute(header_yml, locals()))

  contest_yml = (config.tools_root / 'skel/gitlab-ci-contest.yml').read_text()
  changes = ''
  for problem in problems:
    changes += '      - ' + str(
        problem_source_dir(problem)) + '/problem_statement/**/*\n'
  print(util.substitute(contest_yml, locals()))

  problem_yml = (config.tools_root / 'skel/gitlab-ci-problem.yml').read_text()
  for problem in problems:
    changesdir = problem_source_dir(problem)
    print('\n')
    print(util.substitute(problem_yml, locals()), end='')


def build_parser():
  parser = argparse.ArgumentParser(
      description="""
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
      help='Verbose output; once for what\'s going on, twice for all intermediate output.'
  )
  global_parser.add_argument(
      '-c',
      '--contest',
      help='The contest to use, when running from repository root.')
  global_parser.add_argument(
      '-p',
      '--problem',
      help='The problem to use, when running from repository root.')
  global_parser.add_argument(
      '--no-bar',
      action='store_true',
      help='Do not show progress bars in non-interactive environments.')
  global_parser.add_argument(
      '-e',
      '--error',
      action='store_true',
      help='Print full output of failing commands')
  global_parser.add_argument(
      '-E',
      '--noerror',
      action='store_true',
      help='Hide output of failing commands')
  global_parser.add_argument(
      '--cpp_flags',
      help='Additional compiler flags used for all c++ compilations.')
  global_parser.add_argument(
      '-m',
      '--memory',
      help='The max amount of memory (in bytes) a subprocesses may use. Does not work for java.'
  )
  global_parser.add_argument(
      '--pypy', action='store_true', help='Use pypy instead of cpython.')

  subparsers = parser.add_subparsers(title='actions', dest='action')
  subparsers.required = True

  # New contest
  contestparser = subparsers.add_parser(
      'contest',
      parents=[global_parser],
      help='Add a new contest to the current directory.')
  contestparser.add_argument(
      'contestname', nargs='?', help='The name of the contest')

  # New problem
  problemparser = subparsers.add_parser(
      'problem',
      parents=[global_parser],
      help='Add a new problem to the current directory.')
  problemparser.add_argument(
      'problemname', nargs='?', help='The name of the problem,')
  problemparser.add_argument('--author', help='The author of the problem,')
  problemparser.add_argument(
      '--custom_validation',
      action='store_true',
      help='Use custom validation for this problem.')
  problemparser.add_argument(
      '--default_validation',
      action='store_true',
      help='Use default validation for this problem.')

  # Problem statements
  pdfparser = subparsers.add_parser(
      'pdf', parents=[global_parser], help='Build the problem statement pdf.')
  pdfparser.add_argument(
      '-a',
      '--all',
      action='store_true',
      help='Create problem statements for individual problems as well.')
  pdfparser.add_argument(
      '--web', action='store_true', help='Create a web version of the pdf.')
  pdfparser.add_argument(
      '--cp',
      action='store_true',
      help='Copy the output pdf instead of symlinking it.')
  pdfparser.add_argument(
      '--no_timelimit', action='store_true', help='Do not print timelimits.')

  # Solution slides
  solparser = subparsers.add_parser(
      'solutions',
      parents=[global_parser],
      help='Build the solution slides pdf.')
  solparser.add_argument(
      '-a',
      '--all',
      action='store_true',
      help='Create problem statements for individual problems as well.')

  # Validation
  validate_parser = subparsers.add_parser(
      'validate', parents=[global_parser], help='validate all grammar')
  validate_parser.add_argument(
      'testcases', nargs='*', help='The testcases to run on.')
  input_parser = subparsers.add_parser(
      'input', parents=[global_parser], help='validate input grammar')
  input_parser.add_argument(
      'testcases', nargs='*', help='The testcases to run on.')
  output_parser = subparsers.add_parser(
      'output', parents=[global_parser], help='validate output grammar')
  output_parser.add_argument(
      'testcases', nargs='*', help='The testcases to run on.')

  subparsers.add_parser(
      'constraints',
      parents=[global_parser],
      help='prints all the constraints found in problemset and validators')

  # Stats
  subparsers.add_parser(
      'stats',
      parents=[global_parser],
      help='show statistics for contest/problem')

  # Generate
  genparser = subparsers.add_parser(
      'generate', parents=[global_parser], help='generate answers testcases')
  genparser.add_argument(
      '-f',
      '--force',
      action='store_true',
      help='Overwrite answers that have changed.')
  genparser.add_argument(
      'submission',
      nargs='?',
      help='The program to generate answers. Defaults to first found.')
  genparser.add_argument(
      '-t', '--timelimit', type=int, help='Override the default timeout.')

  # Run
  runparser = subparsers.add_parser(
      'run',
      parents=[global_parser],
      help='Run multiple programs against some or all input.')
  runparser.add_argument(
      '--table',
      action='store_true',
      help='Print a submissions x testcases table for analysis.')
  runparser.add_argument(
      'submissions',
      nargs='*',
      help='optionally supply a list of programs and testcases to run')
  runparser.add_argument(
      '-t', '--timeout', type=int, help='Override the default timeout.')
  runparser.add_argument(
      '--timelimit',
      action='store',
      type=int,
      help='Override the default timelimit.')
  runparser.add_argument(
      '--samples', action='store_true', help='Only run on the samples.')

  # Test
  testparser = subparsers.add_parser(
      'test',
      parents=[global_parser],
      help='Run a single program and print the output.')
  testparser.add_argument(
      'submissions', nargs=1, help='A single submission to run')
  testparser.add_argument(
      'testcases', nargs='*', help='Optionally a list of testcases to run on.')
  testparser.add_argument(
      '--samples', action='store_true', help='Only run on the samples.')
  testparser.add_argument(
      '-t', '--timeout', help='Override the default timeout.')

  # Sort
  subparsers.add_parser(
      'sort',
      parents=[global_parser],
      help='sort the problems for a contest by name')

  # All
  allparser = subparsers.add_parser(
      'all',
      parents=[global_parser],
      help='validate input, validate output, and run programs')
  allparser.add_argument(
      '--cp',
      action='store_true',
      help='Copy the output pdf instead of symlinking it.')
  allparser.add_argument(
      '--no_timelimit', action='store_true', help='Do not print timelimits.')

  # Build DomJudge zip
  zipparser = subparsers.add_parser(
      'zip',
      parents=[global_parser],
      help='Create zip file that can be imported into DomJudge')
  zipparser.add_argument(
      '--skip', action='store_true', help='Skip recreation of problem zips.')
  zipparser.add_argument(
      '-f',
      '--force',
      action='store_true',
      help='Skip validation of input and output files.')
  zipparser.add_argument(
      '--tex',
      action='store_true',
      help='Store all relevant files in the problem statement directory.')
  zipparser.add_argument(
      '--kattis',
      action='store_true',
      help='Make a zip more following the kattis problemarchive.com format.')
  zipparser.add_argument(
      '--no_solutions',
      action='store_true',
      help='Do not compile solutions')

  # Build a zip with all samples.
  subparsers.add_parser(
      'samplezip',
      parents=[global_parser],
      help='Create zip file of all samples.')

  # Build a directory for verification with the kattis format
  subparsers.add_parser(
      'kattis',
      parents=[global_parser],
      help='Build a directory for verification with the kattis format')

  subparsers.add_parser(
      'gitlabci',
      parents=[global_parser],
      help='Print a list of jobs for the given contest.')

  argcomplete.autocomplete(parser)

  return parser


def main():
  # Build Parser
  parser = build_parser()

  # Process arguments
  config.args = parser.parse_args()
  config.verbose = config.args.verbose if hasattr(
      config.args, 'verbose') and config.args.verbose else 0
  action = config.args.action

  if action in ['contest']:
    new_contest(config.args.contestname)
    return

  if action in ['problem']:
    new_problem()
    return

  # Get problems and cd to contest
  problems, level, contest = get_problems()

  if level != 'problem' and action in ['generate', 'test']:
    if action == 'generate':
      print(
          f'{_c.red}Generating output files only works for a single problem.{_c.reset}'
      )
    if action == 'test':
      print(
          f'{_c.red}Testing a submission only works for a single problem.{_c.reset}'
      )
    sys.exit(1)

  if action == 'run':
    if config.args.submissions:
      if level != 'problem':
        print(
            f'{_c.red}Running a given submission only works from a problem directory.{_c.reset}'
        )
        return
      (config.args.submissions,
       config.args.testcases) = split_submissions(config.args.submissions)
    else:
      config.args.testcases = []

  if action in ['stats']:
    stats(problems)
    return

  if action == 'sort':
    print_sorted(problems)
    return

  if action in ['samplezip']:
    export.build_sample_zip(problems)
    return

  if action == 'kattis':
    if level != 'contest':
      print('Only contest level is currently supported...')
      return
    prepare_kattis_directory()
    return

  if action == 'gitlabci':
    create_gitlab_jobs(contest, problems)
    return

  problem_zips = []

  success = True

  for problem in problems:
    if level == 'contest' and action == 'pdf' and not (hasattr(
        config.args, 'all') and config.args.all):
      continue
    print(_c.bold, 'PROBLEM ', problem, _c.reset, sep='')

    # merge problem settings with arguments into one namespace
    problemsettings = util.read_configs(problem)
    settings = argparse.Namespace(**problemsettings)
    for key in vars(config.args):
      if vars(config.args)[key] is not None:
        vars(settings)[key] = vars(config.args)[key]

    if action in ['pdf', 'solutions', 'all']:
      # only build the pdf on the problem level, or on the contest level when
      # --all is passed.
      if level == 'problem' or (level == 'contest' and hasattr(
          config.args, 'all') and config.args.all):
        success &= latex.build_problem_pdf(problem)

    input_validator_ok = False
    if action in ['validate', 'input', 'all']:
      input_validator_ok = validate(problem, 'input', settings)
      success &= input_validator_ok
    if action in ['generate']:
      success &= generate_output(problem, settings)
    if action in ['validate', 'output', 'all']:
      success &= validate(problem, 'output', settings, input_validator_ok)
    if action in ['run', 'all']:
      success &= run_submissions(problem, settings)
    if action in ['test']:
      success &= test_submissions(problem, settings)
    if action in ['constraints']:
      success &= check_constraints(problem, settings)
    if action in ['zip']:
      output = alpha_num(problem.name) + '.zip'
      problem_zips.append(output)
      if not config.args.skip:
        success &= latex.build_problem_pdf(problem)
        if not config.args.force:
          success &= validate(problem, 'input', settings)
          success &= validate(problem, 'output', settings, check_constraints=True)

        # Write to problemname.zip, where we strip all non-alphanumeric from the
        # problem directory name.
        success &= export.build_problem_zip(problem, output, settings)
    if action == 'kattis':
      export.prepare_kattis_problem(problem, settings)

    if len(problems) > 1:
      print()

  if level == 'contest':
    print(f'{_c.bold}CONTEST {contest}{_c.reset}')

    # build pdf for the entire contest
    if action in ['pdf']:
      success &= latex.build_contest_pdf(contest, problems, web=config.args.web)

    if action in ['solutions']:
      success &= latex.build_contest_pdf(contest, problems, solutions=True)

    if action in ['zip']:
      success &= latex.build_contest_pdf(contest, problems)
      success &= latex.build_contest_pdf(contest, problems, web=True)
      if not config.args.no_solutions:
        success &= latex.build_contest_pdf(contest, problems, solutions=True)

      export.build_contest_zip(problem_zips, contest + '.zip', config.args)

  if not success or config.n_error > 0 or config.n_warn > 0:
    sys.exit(1)


if __name__ == '__main__':
  main()
