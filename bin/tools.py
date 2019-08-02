#!/usr/bin/python3
# PYTHON_ARGCOMPLETE_OK
"""Can be run on multiple levels:

    - from the root of the git repository
    - from a contest directory
    - from a problem directory
the tool will know where it is (by looking for the .git directory) and run on
everything inside it

- Ragnar Groot Koerkamp

Parts of this are copied from/based on run_program.py, written by Raymond van Bommel.
"""

import sys
import stat
import argparse
import argcomplete # For automatic shell completions
import os
from pathlib import Path
import datetime
import time
import re
import shutil
import subprocess
import time
import glob
import yaml
import configparser
import io
import zipfile

# Local imports
import export
import config
import util
import latex


# color printing
class Colorcodes(object):

  def __init__(self):
    self.bold = '\033[;1m'
    self.reset = '\033[0;0m'
    self.blue = '\033[;96m'
    self.green = '\033[;32m'
    self.orange = '\033[;33m'
    self.red = '\033[;31m'
    self.white = '\033[;39m'

    self.boldblue = '\033[1;34m'
    self.boldgreen = '\033[1;32m'
    self.boldorange = '\033[1;33m'
    self.boldred = '\033[1;31m'


_c = Colorcodes()


def strip_newline(s):
  if s.endswith('\n'):
    return s[:-1]
  else:
    return s


# A class that draws a progressbar.
# Construct with a constant prefix, the max length of the items to process, and
# the number of items to process.
# When count is None, the bar itself isn't shown.
# Start each loop with bar.start(current_item), end it with bar.done(message).
# Optionally, multiple errors can be logged using bar.log(error). If so, the
# final message on bar.done() will be ignored.
class ProgressBar:
  def __init__(self, prefix, max_len = None, count = None):
    self.prefix = prefix         # The prefix to always print
    self.item_width = max_len    # The max length of the items we're processing
    self.count = count           # The number of items we're processing
    self.i = 0
    self.total_width = shutil.get_terminal_size().columns # The terminal width
    if self.item_width is not None:
      self.bar_width = self.total_width - len(self.prefix) - 2 - self.item_width - 1

  def update(self, count, max_len):
    self.count += count
    self.item_width = max(self.item_width, max_len) if self.item_width else max_len
    if self.item_width is not None:
      self.bar_width = self.total_width - len(self.prefix) - 2 - self.item_width - 1

  def clearline():
    print('\033[K', end='', flush=True)

  def action(prefix, item, width=None):
    if width is None: width = 0
    return f'{_c.blue}{prefix}{_c.reset}: {item:<{width}}'

  def get_prefix(self):
    return ProgressBar.action(self.prefix, self.item, self.item_width)

  def get_bar(self):
    if self.count is None: return ''
    fill = (self.i-1) * (self.bar_width - 2) // self.count
    return '[' + '#' * fill + '-' * (self.bar_width - 2 - fill) + ']'

  def start(self, item = ''):
    self.i += 1
    assert self.count is None or self.i <= self.count

    self.item = item
    self.logged = False
    print(self.get_prefix(), self.get_bar(), end='\r', flush=True)

  # Done can be called multiple times to make multiple persistent lines.
  # Make sure that the message does not end in a newline.
  def log(self, message = ''):
    ProgressBar.clearline()
    self.logged = True
    print(self.get_prefix(), message, flush=True)

  # Return True when something was printed
  def done(self, success = True, message = ''):
    ProgressBar.clearline()
    if self.logged: return False
    if config.verbose or not success:
      self.log(message)
      return True
    return False


def exit(clean=True):
  if clean:
    shutil.rmtree(config.tmpdir)
  sys.exit(1)

# Get the list of relevant problems.
# Either use the provided contest, or check the existence of problem.yaml.
# Returns problems in sorted order by probid in domjudge.ini.
def get_problems(contest = None):
  def is_problem_directory(path):
    return (path / 'problem.yaml').is_file()

  if contest is not None:
    os.chdir(contest)
  level = None
  problems = []
  if is_problem_directory(Path('.')):
    level = 'problem'
    problems = [Path(Path().cwd().name)]
    os.chdir('..') # cd to contest dir.
  else:
    level = 'contest'
    dirs = [p[0] for p in util.sort_problems(Path('.').glob('*/'))]
    for problem in dirs:
      if is_problem_directory(problem):
        problems.append(problem)
    
  contest = Path().cwd().name
  return (problems, level, contest)

# is file at path executable
def is_executable(path):
  return path.is_file() and (path.stat().st_mode & (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH))

def crop_output(output):
  if config.args.noerror: return None
  if config.args.error:   return output

  lines = output.split('\n')
  numlines = len(lines)
  cropped = False
  # Cap number of lines
  if numlines > 10:
    output = '\n'.join(lines[:8])
    output += '\n'
    cropped = True

  # Cap line length.
  if len(output) > 1000:
    output = output[:1000]
    output += ' ...\n' + _c.orange + 'Use -e to show full output or -E to hide it.' + _c.reset
    return output

  if cropped:
    output += _c.orange + str(
        numlines - 8
    ) + ' lines skipped; use -e to show them or -E to hide all output.' + _c.reset
  return output


# Run `command`, returning stderr if the return code is unexpected.
def exec_command(command, expect=0, **kwargs):
  if 'stdout' not in kwargs:
    kwargs['stdout'] = open(os.devnull, 'w')

  timeout = None
  if 'timeout' in kwargs:
    timeout = kwargs['timeout']
    kwargs.pop('timeout')
  process = subprocess.Popen(command, stderr=subprocess.PIPE, **kwargs)
  try:
    (stdout, stderr) = process.communicate(timeout=timeout)
  except subprocess.TimeoutExpired:
    process.kill()
    (stdout, stderr) = process.communicate()

  return (True if process.returncode == expect else process.returncode,
          crop_output(stderr.decode('utf-8')))

def python_interpreter(version):
  if hasattr(config.args, 'pypy') and config.args.pypy:
    if version is 2: return 'pypy'
    print("\n" + _c.red + "Pypy only works for python2!" + _c.reset)
    return None
  else: return 'python' + str(version)

# a function to convert c++ or java to something executable
# returns a command to execute and an optional error message
def build(path):
  # mirror directory structure on tmpfs
  basename = path.name
  ext = path.suffix
  outfile = config.tmpdir / path.with_suffix('')
  outfile.parent.mkdir(parents=True, exist_ok=True)

  compile_command = None
  run_command = None

  if ext == '.c':
    compile_command = [
        'gcc',
        '-I', config.tools_root / 'headers',
        '-std=c11',
        '-Wall',
        '-O2',
        '-o',
        outfile,
        path,
        '-lm'
    ]
    run_command = [outfile]
  elif ext in ('.cc', '.cpp'):
    compile_command = [
        '/usr/bin/g++',
        '-I', config.tools_root / 'headers',
        '-std=c++11',
        '-Wall',
        '-O2',
        '-fdiagnostics-color=always',  # Enable color output
        '-o',
        outfile,
        path
    ]
    run_command = [outfile]
  elif ext == '.java':
    compile_command = ['javac', '-d', config.tmpdir, path]
    run_command = [
        'java', '-enableassertions', '-Xss1024M', '-cp', config.tmpdir, base
    ]
  elif ext in ('.py', '.py2'):
    p = python_interpreter(2)
    if p is not None: run_command = [p, path]
  elif ext == '.py3':
    p = python_interpreter(3)
    if p is not None: run_command = [p, path]
  elif ext == '.ctd':
    ctd_path = config.tools_root / 'checktestdata' / 'checktestdata'
    if ctd_path.is_file():
      run_command = [ ctd_path, path ]
  else:
    return (None, f'{_c.red}Unknown extension \'{ext}\' at file {path}{_c.reset}')

  # Prevent building something twice in one invocation of tools.py.
  message = ''
  if compile_command is not None and not outfile.is_file():
    ret = exec_command(compile_command)
    if ret[0] is not True:
      message = f'{_c.red}FAILED{_c.reset}'
      if ret[1] is not None:
        message += '\n' + strip_newline(ret[1])
      run_command = None

  if run_command is None and message is '':
    message = f'{_c.red}FAILED{_c.reset}'
  return (run_command, message)

# build all files in a directory; return a list of tuples (file, command)
# When 'build' is found, we execute it, and return 'run' as the executable
# This recursively calls itself for subdirectories.
def build_directory(directory, include_dirname=False, bar=None):
  commands = []

  buildfile = directory / 'build'
  runfile = directory / 'run'

  if is_executable(buildfile):
    if bar is None: bar = ProgressBar('Running')
    else: bar.update(1, len(buildfile))
    bar.start(buildfile)

    cur_path = os.getcwd()
    os.chdir(directory)
    if exec_command(['./build'])[0] is not True:
      bar.done(False, f'{_c.red}FAILED{_c.reset}')
      return []
    os.chdir(cur_path)
    if not is_executable(runfile):
      bar.done(False, f'{_c.red}FAILED{_c.reset}: {runfile} must be executable')
      return []
    bar.done()
    return [('run', [runfile])]

  if is_executable(runfile):
    return [('run', [runfile])]

  files = [x for x in directory.glob('*') if x.name[0] is not '.']
  files.sort()

  if len(files) == 0: return commands

  max_file_len = max(len(print_name(path)) for path in files)
  if bar is None: bar = ProgressBar('Building', max_file_len, len(files))
  else: bar.update(len(files), max_file_len)

  for path in files:
    bar.start(print_name(path))

    basename = path.name
    if basename == 'a.out':
      bar.done()
      continue

    if include_dirname:
      dirname = path.parent.name
      name = Path(dirname) / basename
    else:
      name = basename

    if path.is_dir():
      bar.done()
      r = build_directory(path, include_dirname=True, bar=bar)
      commands += r
      continue
    elif is_executable(path):
      commands.append((name, [path]))
    else:
      ext = path.suffix
      if ext in config.BUILD_EXTENSIONS:
        run_command, message = build(path)
        if run_command != None:
          commands.append((name, run_command))
        else:
          bar.log(message)
      else:
        bar.log(f'{_c.red}Extension \'{ext}\' is not supported for file {path}{_c.reset}')

    bar.done()

  return commands


# Drops the first two path components <problem>/<type>/
def print_name(path):
  return str(Path(*path.parts[2:]))



def get_validators(problem, validator_type):
  return build_directory(problem / (validator_type + '_validators'))


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
def validate(problem, validator_type, settings):
  if not validator_type in ['input', 'output']:
    print('Validator type must be `input` or `output`!')
    exit()

  if validator_type == 'output' and settings.validation == 'custom':
    return True

  validators = get_validators(problem, validator_type)
  # validate testcases without answer files
  testcases = util.get_testcases(problem, validator_type == 'output')
  ext = '.in' if validator_type == 'input' else '.ans'

  if len(validators) == 0:
    return False
  if len(testcases) == 0:
    return True

  success = True

  action = 'Validating ' + validator_type

  # Flags are only needed for output validators; input validators are
  # sensitive by default.
  flags = []
  if validator_type == 'output':
    flags = ['case_sensitive', 'space_change_sensitive']

  max_testcase_len = max(
      [len(print_name(testcase) + ext) for testcase in testcases])

  # validate the testcases
  bar = ProgressBar(action, max_testcase_len, len(testcases))
  for testcase in testcases:
    bar.start(print_name(testcase)+ext)
    for validator in validators:
      # simple `program < test.in` for input validation and ctd output validation
      if validator_type == 'input' or Path(validator[0]).suffix == '.ctd':
        ret = exec_command(
            validator[1] + flags,
            expect=config.RTV_AC,
            stdin=testcase.with_suffix(ext).open())
      else:
        # more general `program test.in test.ans feedbackdir < test.in/ans` output validation otherwise
        ret = exec_command(
            validator[1] + [testcase.with_suffix('.in'),
              testcase.with_suffix('.ans'), config.tmpdir] +
            flags,
            expect=config.RTV_AC,
            stdin=testcase.with_suffix(ext).open())

      # Failure?
      if ret[0] is not True:
        success = False
        message = _c.red + 'FAILED ' + validator[0] + _c.reset

        # Print error message?
        if ret[1] is not None:
          message += '  ' + _c.orange + strip_newline(ret[1]) + _c.reset

        bar.log(message)
    bar.done()

  if not config.verbose and success:
    print(ProgressBar.action(action, f'{_c.green}Done{_c.reset}'))
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
      ('ini', 'domjudge-problem.ini'),
      ('tex', 'problem_statement/problem.tex'),
      ('sol', 'problem_statement/solution.tex'),
      ('   Ival', ['input_validators/*.ctd', 'input_validators/*.cpp']),
      ('Oval', ['output_validators/*.ctd', 'output_validators/*.cpp']),
      ('   sample', 'data/sample/*.in', 2),
      ('secret', 'data/secret/*.in', 15, 50),
      ('    AC', 'submissions/accepted/*', 3),
      (' WA', 'submissions/wrong_answer/*', 2),
      ('TLE', 'submissions/time_limit_exceeded/*', 1),
      ('    java', 'submissions/accepted/*.java'),
      ('py2', ['submissions/accepted/*.py', 'submissions/accepted/*.py2']),
      ('py3', 'submissions/accepted/*.py3'),
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
      for p in problem.glob(path):
        hidden = False
        for d in p.parts:
          if d[0] == '.':
            hidden = True
        if hidden: continue
        # Exclude files containing 'TODO: Remove'.
        if p.is_file():
          with p.open() as file:
            data = file.read()
            if data.find('TODO: Remove') == -1:
              cnt += 1
      return cnt

    counts = [count(s[1]) for s in stats]
    for i in range(0, len(stats)):
      cumulative[i] = cumulative[i] + counts[i]
    print(format_string.format(
            problem.name,
            *[get_stat(counts[i],
                True if len(stats[i]) <= 2 else stats[i][2],
                None if len(stats[i]) <= 3 else stats[i][3])
              for i in range(len(stats))]))

  # print the cumulative count
  print('-' * len(header))
  print(format_string.format(*(
      ['TOTAL'] + list(map(lambda x: get_stat(x, False), cumulative)))))


# returns a map {answer type -> [(name, command)]}
def get_submissions(problem):
  dirs = list(problem.glob('submissions/*/'))
  commands = {}

  max_dir_len = max(len(d.name) for d in dirs)

  bar = ProgressBar('Building', max_dir_len, len(dirs))

  for d in dirs:
    dirname = d.name
    bar.start(dirname)
    bar.done()
    if not dirname.upper() in config.PROBLEM_OUTCOMES:
      continue
    # include directory in submission name
    commands[dirname.upper()] = build_directory(d, True, bar=bar)

  if config.verbose: print()

  return commands


def quick_diff(ans, out):
  ans = ans.decode()
  out = out.decode()
  if ans.count('\n') <= 1 and out.count('\n') <= 1:
    return 'Got ' + strip_newline(out) + ' wanted ' + strip_newline(ans)
  else:
    return ''


# return: (success, remark)
def default_output_validator(ansfile, outfile, settings):
  # settings: floatabs, floatrel, case_sensitive, space_change_sensitive
  with open(ansfile, 'rb') as f:
    indata1 = f.read()

  with open(outfile, 'rb') as f:
    indata2 = f.read()

  if indata1 == indata2:
    return (True, '')

  if not settings.case_sensitive:
    # convert to lowercase...
    data1 = indata1.lower()
    data2 = indata2.lower()

    if data1 == data2:
      return (True, 'case')
  else:
      data1 = indata1
      data2 = indata2

  if settings.space_change_sensitive and settings.floatabs == None and settings.floatrel == None:
    return (False, quick_diff(data1, data2))

  if settings.space_change_sensitive:
    words1 = re.split(rb'\b(\S+)\b', data1)
    words2 = re.split(rb'\b(\S+)\b', data2)
  else:
    words1 = re.split(rb'[ \n]+', data1)
    words2 = re.split(rb'[ \n]+', data2)
    if len(words1)>0 and words1[-1] == b'': words1.pop()
    if len(words2)>0 and words2[-1] == b'': words2.pop()
    if len(words1)>0 and words1[0] == b'': words1.pop(0)
    if len(words2)>0 and words2[0] == b'': words2.pop(0)

  if words1 == words2:
    if not settings.space_change_sensitive:
      return (True, 'white space')
    else:
      print(
          'Strings became equal after space sensitive splitting! Something is wrong!'
      )
      exit()

  if settings.floatabs is None and settings.floatrel is None:
    return (False, quick_diff(data1, data2))

  if len(words1) != len(words2):
    return (False, quick_diff(data1, data2))

  peakabserr = 0
  peakrelerr = 0
  for (w1, w2) in zip(words1, words2):
    if w1 != w2:
      try:
        f1 = float(w1)
        f2 = float(w2)
        abserr = abs(f1 - f2)
        relerr = abs(f1 - f2) / f1
        peakabserr = max(peakabserr, abserr)
        peakrelerr = max(peakrelerr, relerr)
        if ((settings.floatabs is None or abserr > settings.floatabs) and
            (settings.floatrel is None or relerr > settings.floatrel)):
          return (False, quick_diff(data1, data2))
      except ValueError:
        return (False, quick_diff(data1, data2))

  return (True, 'float: abs {0:.2g} rel {1:.2g}'.format(peakabserr, peakrelerr))


# call output validators as ./validator in ans feedbackdir additional_arguments < out
# return (success, remark)
def custom_output_validator(testcase, outfile, settings, output_validators):
  flags = []
  if settings.space_change_sensitive:
    flags += ['space_change_sensitive']
  if settings.case_sensitive:
    flags += ['case_sensitive']

  for output_validator in output_validators:
    ret = None
    with open(outfile, 'rb') as outf:
      ret = exec_command(
          output_validator[1] + [testcase.with_suffix('.in'),
            testcase.with_suffix('.ans'), config.tmpdir] +
          flags,
          expect=config.RTV_AC,
          stdin=outf)
    # Read judgemessage if present
    judgemessagepath = config.tmpdir / 'judgemessage.txt'
    judgemessage = ''
    if judgemessagepath.is_file():
      with judgemessagepath.open() as judgemessagefile:
        judgemessage = judgemessagefile.read()
      os.unlink(judgemessagepath)
    
    if ret[0] is True:
      continue
    if ret[0] == config.RTV_WA:
      return (False, ret[1] + judgemessage)
    print('ERROR in output validator ', output_validator[0], ' exit code ',
          ret[0], ': ', ret[1])
    exit(False)
  return (True, judgemessage)


# Return (ret, timeout (True/False), duration)
def run_testcase(run_command, testcase, outfile, tle=None):
  timeout = False
  with testcase.with_suffix('.in').open('rb') as inf:
    with open(outfile, 'wb') as outf:
      tstart = time.monotonic()
      try:
        # Double the tle to check for solutions close to the required bound
        # ret = True or ret = (code, error)
        ret = exec_command(
            run_command,
            expect=0,
            stdin=inf,
            stdout=outf,
            timeout=float(config.args.timeout) if hasattr(config.args, 'timeout') and
            config.args.timeout else (2 * tle if tle is not None else None))
      except subprocess.TimeoutExpired:
        timeout = True
        ret = (True, None)
      tend = time.monotonic()

  duration = tend - tstart
  if tle and duration > tle:
    timeout = True
  return (ret, timeout, duration)


# return (verdict, time, remark)
def process_testcase(run_command,
                     testcase,
                     outfile,
                     settings,
                     output_validators,
                     silent=False,
                     printnewline=False):

  run_ret, timeout, duration = run_testcase(run_command, testcase, outfile,
                                        settings.timelimit)
  verdict = None
  remark = ''
  if timeout:
    verdict = 'TIME_LIMIT_EXCEEDED'
  elif run_ret[0] is not True:
    verdict = 'RUN_TIME_ERROR'
    remark = 'Exited with code ' + str(run_ret[0]) + ':\n' + run_ret[1]
  else:
    if settings.validation == 'default':
      val_ret = default_output_validator(testcase.with_suffix('.ans'), outfile, settings)
    elif settings.validation == 'custom':
      val_ret = custom_output_validator(testcase, outfile, settings,
                                    output_validators)
    else:
      print(_c.red + 'Validation type must be one of `default` or `custom`' +
              _c.reset)
      exit()
    verdict = 'ACCEPTED' if val_ret[0] else 'WRONG_ANSWER'
    remark = val_ret[1]

    if run_ret[1] is not None and (hasattr(config.args, 'output') and config.args.output):
      if verdict == 'WRONG_ANSWER' or config.args.error:
          remark += '\n' + crop_output(run_ret[1]) + '\n'

  return (verdict, duration, remark)


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
  max_total_length = max(max([len(print_name(testcase)) for testcase in testcases]), 15) + max_submission_len
  max_testcase_len = max_total_length - len(str(submission[0]))

  printed = False
  bar = ProgressBar(action, max_testcase_len, len(testcases))

  for testcase in testcases:
    bar.start(print_name(testcase))
    outfile = config.tmpdir / 'test.out'
    #silent = expected != 'ACCEPTED'
    silent = False
    verdict, runtime, remark = \
        process_testcase(submission[1], testcase, outfile, settings, output_validators,
                silent, need_newline)
    verdict_count[verdict] += 1

    time_total += runtime
    time_max = max(time_max, runtime)

    if table_dict is not None:
      table_dict[testcase] = verdict == 'ACCEPTED'

    got_expected = verdict == 'ACCEPTED' or verdict == expected
    color = _c.green if got_expected else _c.red
    message = '{:6.3f}s '.format(runtime) + color + verdict + _c.reset
    if remark:
        message += '  ' + _c.orange + strip_newline(remark) + _c.reset

    printed |= bar.done(got_expected, message)

    if not config.verbose and verdict in ['TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR']:
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
  print(f'{action:<{max_total_length-6}} {boldcolor}max/avg {time_max:6.3f}s {time_avg:6.3f}s {color}{verdict}')

  if printed: print()

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
  # Require both in and ans files
  if hasattr(settings, 'testcases') and settings.testcases:
    testcases = [problem/t for t in settings.testcases]
  else:
    testcases = util.get_testcases(problem, True)

  if len(testcases) == 0:
    print(_c.red + 'No testcases found!' + _c.reset)
    return False


  output_validators = None
  if settings.validation == 'custom':
    output_validators = get_validators(problem, 'output')

  if hasattr(settings, 'submissions') and settings.submissions:
    submissions = {
        'ACCEPTED': [],
        'WRONG_ANSWER': [],
        'TIME_LIMIT_EXCEEDED': [],
        'RUN_TIME_ERROR': []
    }
    max_submission_len = max(len(print_name(problem / s)) for s in settings.submissions)
    bar = ProgressBar('Building', max_submission_len, len(settings.submissions)) 

    for submission in settings.submissions:
      path = problem / submission
      bar.start(print_name(path))

      if path.is_dir():
        bar.done()
        commands = build_directory(path, True, bar)
        for c in commands:
          submissions[get_submission_type(c[0])].append(c)
        continue

      if path.is_file():
        run_command, message = build(path)
        bar.done(run_command is not None, message)
        if run_command:
          submissions[get_submission_type(path)].append((print_name(path), run_command))
        continue

      bar.done(False, f'{_c.red}FAILED{_c.reset} {path} is not a file or directory.')

    if config.verbose: print()
  else:
    submissions = get_submissions(problem)

  max_submission_len = max([0] + 
      [len(str(x[0])) for cat in submissions for x in submissions[cat]])

  success = True
  verdict_table = []
  for verdict in config.PROBLEM_OUTCOMES:
    if verdict in submissions:
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
    single_verdict = lambda row, testcase: str(int(row[testcase])) if testcase in row else '-'
    make_verdict = lambda tc: ''.join(map(lambda row: single_verdict(row, testcase), verdict_table))
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

    print('\nVerdict analysis table. Submissions are ordered as above.')
    for testcase in testcases:
      print('{:<60}'.format(testcase), end=' ')
      resultant = make_verdict(testcase)
      print(resultant, end='  ')
      if resultant in resultant_id:
        print(str.format('(Type {})', resultant_id[resultant]), end='')
      print(end='\n')

  return success


def generate_output(problem, settings):
  if hasattr(settings, 'submission') and settings.submission:
    submission = problem / settings.submission
  else:
    # only get one accepted submission
    submissions = list(problem.glob('submissions/accepted/*'))
    if len(submissions) == 0:
      print('No submission found for this problem!')
      exit()
    submissions.sort()
    # Look fora c++ solution if available.
    submission = None
    for s in submissions:
      # Skip files containing 'NO_GENERATE'.
      with open(s) as submission_file:
        if submission_file.read().find('NO_GENERATE') != -1:
          continue
      if s.suffix == '.cpp':
        submission = s
        break
      else:
        if submission is None:
          submission = s

  # build submission
  bar = ProgressBar('Building')
  bar.start(print_name(submission))
  run_command, message = build(submission)
  bar.done(False, message)
  if config.verbose: print()

  # get all testcases with .in files
  testcases = util.get_testcases(problem, False)

  nsame = 0
  nchange = 0
  nskip = 0
  nnew = 0
  nfail = 0

  max_testcase_len = max([len(print_name(testcase)) for testcase in testcases])

  bar = ProgressBar('Generate', max_testcase_len, len(testcases))

  for testcase in testcases:
    bar.start(print_name(testcase))

    outfile = config.tmpdir / 'test.out'
    try:
      os.unlink(outfile)
    except OSError:
      pass
    ret, timeout, duration = run_testcase(run_command, testcase, outfile,
                                          settings.timelimit)
    message = ''
    same = False
    if ret[0] is not True or timeout is True:
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
        if default_output_validator(testcase.with_suffix('.ans'), outfile,
                                    compare_settings)[0]:
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

  print()
  print('Done:')
  print('%d testcases new' % nnew)
  print('%d testcases changed' % nchange)
  print('%d testcases skipped' % nskip)
  print('%d testcases unchanged' % nsame)
  print('%d testcases failed' % nfail)



def print_sorted(problems):
  prefix = config.args.contest + '/' if config.args.contest else ''
  for problem in util.sort_problems(problems):
    print(prefix + problem[0])

"""
DISCLAIMER:
  This tool was only made to check constraints faster.
  However it is not guaranteed it will find all constraints.
  Checking constraints by yourself is probably the best way.
"""
def check_constraints(problem, settings):
  vinput = problem / 'input_validators/input_validator.cpp'
  voutput = problem / 'output_validators/output_validator.cpp'

  cpp_statement = re.compile(
      '^(const\s+|constexpr\s+)?(int|string|long long|float|double)\s+(\w+)\s*[=]\s*(.*);$'
  )

  defs = []
  for validator in [vinput, voutput]:
    with open(validator) as file:
      for line in file:
        mo = cpp_statement.search(line)
        if mo is not None:
          defs.append(mo)

  defs_validators = [(mo.group(3), mo.group(4)) for mo in defs]

  statement = problem / 'problem_statement/problem.tex'
  latex_define = re.compile('^\\newcommand{\\\\(\w+)}{(.*)}$')
  latex_define = re.compile('{\\\\(\w+)}{(.*)}')

  defs.clear()
  with open(statement) as file:
    for line in file:
      mo = latex_define.search(line)
      if mo is not None:
        defs.append(mo)

  defs_statement = [(mo.group(1), mo.group(2)) for mo in defs]

  # print all the definitions.
  nl = len(defs_validators)
  nr = len(defs_statement)

  print(
      '{:^30}|{:^30}'.format('  VALIDATORS', '      PROBLEM STATEMENT'),
      sep='')
  for i in range(0, max(nl, nr)):
    if i < nl:
      print(
          '{:>15}  {:<13}'.format(defs_validators[i][1], defs_validators[i][0]),
          sep='',
          end='')
    else:
      print('{:^30}'.format(''), sep='', end='')
    print('|', end='')
    if i < nr:
      print(
          '{:>15}  {:<13}'.format(defs_statement[i][1], defs_statement[i][0]),
          sep='',
          end='')
    else:
      print('{:^30}'.format(''), sep='', end='')
    print()

  return True


# Returns the alphanumeric version of a string, removing all characters that are not a-zA-Z0-9
def alpha_num(string, allow_dash = False):
  if allow_dash:
    return re.sub(r'[^a-z0-9_-]', '', string.lower().replace(' ', '-'))
  else:
    return re.sub(r'[^a-z0-9]', '', string.lower())


# Creates a symlink if it not exists, else it does nothing
# the symlink will be created at link_name, pointing to target
def symlink_quiet(target, link_name):
  if link_name.is_symlink():
    link_name.unline()
  if not link_name.exists():
    link_name.symlink_to(target)
  # if it existed and is not a symlink, do nothing


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


def substitute_file_variables(path, variables):
  with path.open() as infile:
    data = infile.read()

  for key in variables:
    if variables[key] == None: continue
    data = data.replace('{%'+key+'%}', variables[key])

  with path.open('w') as outfile:
    outfile.write(data)

def substitute_dir_variables(dirname, variables):
  for path in dirname.rglob('*'):
    if path.is_file():
      substitute_file_variables(path, variables)

def new_contest(name):
  # Ask for all required infos.
  title = ask_variable('name', name)
  subtitle = ask_variable('subtitle', '')
  dirname = ask_variable('dirname', alpha_num(title, allow_dash = True))
  author = ask_variable('author', f'The {title} jury')
  testsession = ('% ' if ask_variable('testsession?', 'n (y/n)')[0] == 'n' else
                 '') +  '\\testsession'
  year = ask_variable('year', str(datetime.datetime.now().year))
  source = ask_variable('source', title)
  source_url = ask_variable('source url', '')
  license = ask_variable('license', 'cc by-sa')
  rights_owner = ask_variable('rights owner', 'author')

  shutil.copytree(config.tools_root / 'skel/contest', dirname, symlinks=True)

  substitute_dir_variables(dirname, locals())


def new_problem():
    problemname = config.args.problemname if config.args.problemname else ask_variable('problem name')
    dirname = ask_variable('dirname', alpha_num(problemname, True))
    author = config.args.author if config.args.author else ask_variable('author', config.args.author)

    if config.args.custom_validation:
      validation = 'custom'
    elif config.args.default_validation:
      validation = 'default'
    else:
      validation = ask_variable('validation', 'default')

    # Read settings from the contest-level yaml file.
    variables = {'problemname': problemname, 'dirname': dirname, 'author':
        author, 'validation': validation}
    yamlfilepath = Path('contest.yaml')
    if yamlfilepath.is_file():
      with yamlfilepath.open() as yamlfile:
        try:
          contest_vars = yaml.load(yamlfile)
          for key in contest_vars:
            variables[key] = '' if contest_vars[key] is None else contest_vars[key]
        except:
          pass

    for key in variables:
      print(key, ' -> ', variables[key])

    shutil.copytree(config.tools_root / 'skel/problem', dirname, symlinks=True)

    substitute_dir_variables(dirname, variables)


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
      help=
      'Verbose output; once for what\'s going on, twice for all intermediate output.'
  )
  global_parser.add_argument(
      '-c',
      '--contest',
      help='The contest to use, when running from repository root.')
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

  subparsers = parser.add_subparsers(title='actions', dest='action')
  subparsers.required = True

  # New contest
  contestparser = subparsers.add_parser(
      'contest',
      parents=[global_parser],
      help='Add a new contest to the current directory.')
  contestparser.add_argument('contestname', nargs='?', help='The name of the contest')

  # New problem
  problemparser = subparsers.add_parser(
      'problem',
      parents=[global_parser],
      help='Add a new problem to the current directory.')
  problemparser.add_argument('problemname', nargs='?', help='The name of the problem,')
  problemparser.add_argument('--author', help='The author of the problem,')
  problemparser.add_argument('--custom_validation', action='store_true', help='Use custom validation for this problem.')
  problemparser.add_argument('--default_validation', action='store_true', help='Use default validation for this problem.')

  # Problem statements
  pdfparser = subparsers.add_parser(
      'pdf',
      parents=[global_parser],
      help='Build the problem statement pdf.')
  pdfparser.add_argument(
      '-a',
      '--all',
      action='store_true',
      help='Create problem statements for individual problems as well.')
  pdfparser.add_argument(
      '--web',
      action='store_true',
      help='Create a web version of the pdf.')

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
  subparsers.add_parser(
      'validate',
      parents=[global_parser],
      help='validate all grammar')
  subparsers.add_parser(
      'input',
      parents=[global_parser],
      help='validate input grammar')
  subparsers.add_parser(
      'output',
      parents=[global_parser],
      help='validate output grammar')
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
      'generate',
      parents=[global_parser],
      help='generate answers testcases')
  genparser.add_argument(
      '-f',
      '--force',
      action='store_true',
      help='Overwrite answers that have changed.')
  genparser.add_argument(
      'submission',
      nargs='?',
      help='The program to generate answers. Defaults to first found.')

  # Run
  runparser = subparsers.add_parser(
      'run', parents=[global_parser], help='run programs and check answers')
  runparser.add_argument(
      '--table',
      action='store_true',
      help='Print a submissions x testcases table for analysis.')
  runparser.add_argument(
      'submissions',
      nargs='*',
      help='optionally supply a list of programs and testcases to run')
  runparser.add_argument(
      '-t', '--timeout', help='Override the default timeout.')
  runparser.add_argument(
      '-o', '--output', action='store_true', help='Print output of WA submissions.')
  runparser.add_argument(
      '--pypy', action='store_true', help='Use pypy instead of cpython.')

  # Sort
  subparsers.add_parser(
      'sort',
      parents=[global_parser],
      help='sort the problems for a contest by name')

  # All
  subparsers.add_parser(
      'all',
      parents=[global_parser],
      help='validate input, validate output, and run programs')

  # Build DomJudge zip
  zipparser = subparsers.add_parser(
      'zip',
      parents=[global_parser],
      help='Create zip file that can be imported into DomJudge')
  zipparser.add_argument(
      '-s',
      '--skip',
      action='store_true',
      help='Skip recreation of problem zips.')
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

  argcomplete.autocomplete(parser)

  return parser


def main():
  # Build Parser
  parser = build_parser()

  # Process arguments
  config.args = parser.parse_args()
  config.verbose = config.args.verbose if hasattr(config.args, 'verbose') and config.args.verbose else 0
  action = config.args.action

  if action in ['contest']:
    new_contest(config.args.contestname)
    exit()

  if action in ['problem']:
    new_problem(config.args)
    exit()

  # Get problems and cd to contest
  problems, level, contest = get_problems(config.args.contest)

  if action in ['generate']:
    if level != 'problem':
      print(f'{_c.red}Generating output files only works for a single problem.{_c.reset}')
      exit()

  if action == 'run':
    if config.args.submissions:
      if level != 'problem':
        print('{_c.red}Running a given submission only works from a problem directory.{_c.reset}')
        exit()
      (config.args.submissions, config.args.testcases) = split_submissions(config.args.submissions)
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
    if level != "contest":
      print("Only contest level is currently supported...")
      exit()
    prepare_kattis_directory()

  problem_zips = []

  success = True
  for problem in problems:
    print(_c.bold, 'PROBLEM ', problem, _c.reset, sep='')

    # merge problem settings with arguments into one namespace
    problemsettings = util.read_configs(problem)
    settings = config.args
    for key in problemsettings:
      vars(settings)[key] = problemsettings[key]

    if action in ['pdf', 'solutions']:
      # only build the pdf on the problem level
      success &= latex.build_problem_pdf(problem, config.args.all or level == 'problem')

    if action in ['validate', 'input', 'all']:
      success &= validate(problem, 'input', settings)
    if action in ['generate', 'all']:
      generate_output(problem, settings)
    if action in ['validate', 'output', 'all']:
      success &= validate(problem, 'output', settings)
    if action in ['run', 'all']:
      success &= run_submissions(problem, settings)
    if action in ['constraints']:
      success &= check_constraints(problem, settings)
    if action in ['zip']:
      output = alpha_num(problem.name) + '.zip'
      problem_zips.append(output)
      if not config.args.skip:
        success &= latex.build_problem_pdf(problem, True)
        if not config.args.force:
          success &= validate(problem, 'input', settings)
          success &= validate(problem, 'output', settings)

        # Write to problemname.zip, where we strip all non-alphanumeric from the
        # problem directory name.
        success &= export.build_problem_zip(problem, output, settings)
    if action == 'kattis':
      export.prepare_kattis_problem(problem, settings)

    if len(problems) > 1:
      print()

  # build pdf for the entire contest
  if action in ['pdf'] and level == 'contest':
    # Run 3 times, to fix the TOC.
    success &= latex.build_contest_pdf(contest, problems, web=config.args.web)
    success &= latex.build_contest_pdf(contest, problems, web=config.args.web)
    success &= latex.build_contest_pdf(contest, problems, web=config.args.web)

  if action in ['solutions'] and level == 'contest':
    success &= latex.build_contest_pdf(contest, problems, solutions=True)

  if action in ['zip'] and config.args.contest:
    success &= latex.build_contest_pdf(contest, problems)
    success &= latex.build_contest_pdf(contest, problems)
    success &= latex.build_contest_pdf(contest, problems)
    success &= latex.build_contest_pdf(contest, problems, web=True)
    success &= latex.build_contest_pdf(contest, problems, solutions=True)

    export.build_contest_zip(problem_zips, contest + '.zip', config.args)

  if not success:
    exit()

if __name__ == '__main__':
  main()
shutil.rmtree(config.tmpdir)

# vim: et ts=2 sts=2 sw=2:
