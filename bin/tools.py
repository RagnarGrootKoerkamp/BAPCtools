#!/usr/bin/python3
"""Can be run on multiple levels:

    - from the root of the git repository
    - from a contest directory
    - from a problem directory
the tool will know where it is (by looking for the .git directory) and run on
everything inside it

Needs work to make is work on Windows.
In particular regarding os.path.join instead of joining strings with /

- Ragnar

Parts of this are copied from/based on run_program.py, written by Raymond.
"""

import sys
import stat
import argparse
import os
import re
import shutil
import subprocess
import tempfile
import time
import glob
import yaml
import configparser
import io
import zipfile
from build_zip import build_problem_zip, build_contest_zip

# some aliases
from glob import glob

# return values
rtv_ac = 42
rtv_wa = 43

build_extensions = ['.c', '.cc', '.cpp', '.java', '.py', '.py2', '.py3', '.ctd']
problem_outcomes = [
    'ACCEPTED', 'WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR'
]
tmpdir = tempfile.mkdtemp(prefix='bapctools_')

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD = 4

TOOLS_ROOT = ''

# this is lifted for convenience
args = None
verbose = False


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


def clearline():
  print('\033[K', end='', flush=True)


def print_action(action, state=None, end='\r'):
  clearline()
  print(_c.blue, action, _c.reset, sep='', end='')
  if state is None:
    print(end=end)
  else:
    print(': ', state, sep='', end=end)


def get_bar(i, total, length):
  fill = i * (length - 2) // total
  return '[' + '#' * fill + '-' * (length - 2 - fill) + ']'


def print_action_bar(action, i, total, state=None, max_state_len=None):
  if verbose:
    print_action(action, state, end='\r')
    return

  clearline()
  width = shutil.get_terminal_size().columns
  print(_c.blue, action, _c.reset, sep='', end='')
  if state is None:
    print(end=' ')
    width -= len(action) + 1
  else:
    print(': ', state, sep='', end=' ')
    if max_state_len is None:
      width -= len(action) + len(state) + 3
    else:
      x = max(len(state), max_state_len)
      width -= len(action) + x + 3
      print(' ' * (x - len(state)), end='')
  print(get_bar(i, total, width), end='\r', flush=True)


def add_newline(s):
  if s.endswith('\n'):
    return s
  else:
    return s + '\n'


def strip_newline(s):
  if s.endswith('\n'):
    return s[:-1]
  else:
    return s


def exit(clean=True):
  if clean:
    shutil.rmtree(tmpdir)
  sys.exit(1)


# get the list of relevant problems,
# and cd to a directory at contest level
# the list returned has unspecified order
def get_problems(contest):
  if os.path.isdir('.git'):
    if contest is None:
      print('A contest must be supplied when running from the repository root!')
      exit()
    os.chdir(contest)
  elif os.path.isdir('../.git'):
    pass
  elif os.path.isdir('../../.git'):
    problems = [os.path.basename(os.getcwd())]
    os.chdir('..')
    return (problems, 'problem', os.path.basename(os.getcwd()))
  else:
    print(
        "ERROR: Can't determine git root directory; run this from problem, contest, or root"
    )
    exit()

  # return list of problems in contest directory
  return ([os.path.normpath(p[0]) for p in sort_problems(glob('*/'))],
          'contest', os.path.basename(os.getcwd()))


# read problem settings from config files
def read_configs(problem):
  # some defaults
  settings = {
      'timelimit': 1,
      'name': '',
      'floatabs': None,
      'floatrel': None,
      'validation': 'default',
      'case_sensitive': False,
      'space_change_sensitive': False,
      'validator_flags': None
  }

  # parse problem.yaml
  yamlpath = os.path.join(problem, 'problem.yaml')
  if os.path.isfile(yamlpath):
    with open(yamlpath) as yamlfile:
      try:
        config = yaml.load(yamlfile)
        for key, value in config.items():
          settings[key] = value
      except:
        pass

  # parse validator_flags
  if 'validator_flags' in settings and settings['validator_flags']:
    flags = settings['validator_flags'].split(' ')
    i = 0
    while i < len(flags):
      if flags[i] in ['case_sensitive', 'space_change_sensitive']:
        settings[flags[i]] = True
      elif flags[i] == 'float_absolute_tolerance':
        settings['floatabs'] = float(flags[i + 1])
        i += 1
      elif flags[i] == 'float_relative_tolerance':
        settings['floatrel'] = float(flags[i + 1])
        i += 1
      elif flags[i] == 'float_tolerance':
        settings['floatabs'] = float(flags[i + 1])
        settings['floatrel'] = float(flags[i + 1])
        i += 1
      i += 1

  # parse domjudge-problem.ini
  if os.path.isfile(os.path.join(problem, 'domjudge-problem.ini')):
    with open(os.path.join(problem, 'domjudge-problem.ini')) as f:
      for line in f.readlines():
        key, var = line.strip().split('=')
        var = var[1:-1]
        settings[key] = float(var) if key == 'timelimit' else var

  return settings


# is file at path executable
def is_executable(path):
  return os.path.exists(path) and (os.stat(path).st_mode &
                                   (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH))

def crop_output(output):
  if args.noerror: return None
  if args.error:   return output

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


# a function to convert c++ or java to something executable
# returns a command to execute
def build(path, action=None):
  if action is not None:
    print_action(action, print_name(path))

  # mirror directory structure on tmpfs
  basename = os.path.basename(path)
  (base, ext) = os.path.splitext(basename)
  exefile = os.path.join(tmpdir, os.path.dirname(path), base)
  os.makedirs(os.path.dirname(exefile), exist_ok=True)
  if ext == '.c':
    compile_command = [
        'gcc', '-std=c11', '-Wall', '-O2', '-o', exefile, path, '-lm'
    ]
    run_command = [exefile]
  elif ext in ('.cc', '.cpp'):
    compile_command = [
        'g++',
        '-std=c++11',
        '-Wall',
        '-O2',
        '-fdiagnostics-color=always',  # Enable color output
        '-o',
        exefile,
        path
    ]
    run_command = [exefile]
  elif ext == '.java':
    compile_command = ['javac', '-d', tmpdir, path]
    run_command = [
        'java', '-enableassertions', '-Xss1024M', '-cp', tmpdir, base
    ]
  elif ext in ('.py', '.py2'):
    compile_command = None
    run_command = ['python2', path]
  elif ext == '.py3':
    compile_command = None
    run_command = ['python3', path]
  elif ext == '.ctd':
    compile_command = None
    run_command = [
        os.path.join(TOOLS_ROOT, 'checktestdata', 'checktestdata'), path
    ]
  else:
    print(path, 'has unknown extension', ext)
    exit()

  # prevent building something twice
  if compile_command is not None and not os.path.isfile(exefile):
    ret = exec_command(compile_command)
    if ret[0] is not True:
      print_action(
          action if action is not None else 'Building',
          print_name(path) + ' ' + _c.red + 'FAILED' + _c.reset,
          end='\n')
      if ret[1] is not None:
        print(_c.reset, ret[1], sep='', end='\n', flush=True)
      return None

  return run_command

# build all files in a directory; return a list of tuples (file, command)
# When 'build' is found, we execute it, and return 'run' as the executable
def build_directory(directory, include_dirname=False, action=None):
  commands = []

  buildfile = os.path.join(directory, 'build')
  runfile = os.path.join(directory, 'run')

  if is_executable(buildfile):
    if action is not None:
      print_action(action, buildfile)

    cur_path = os.getcwd()
    os.chdir(directory)
    if exec_command(['./build'])[0] is not True:
      print(path, 'failed!')
      exit()
    os.chdir(cur_path)
    if not is_executable(runfile):
      print('after running', path, ',', runfile, 'must be a valid executable!')
      exit()
    return [('run', [runfile])]

  if is_executable(runfile):
    return [('run', [runfile])]

  files = glob(os.path.join(directory, '*'))
  files.sort()
  for path in files:
    basename = os.path.basename(path)
    if basename == 'a.out':
      continue

    if include_dirname:
      dirname = os.path.basename(os.path.dirname(path))
      name = os.path.join(dirname, basename)
    else:
      name = basename

    if is_executable(path):
      commands.append((name, [path]))
    else:
      ext = os.path.splitext(name)[1]
      if ext in build_extensions:
        run_command = build(path, action=action)
        if run_command != None:
          commands.append((name, run_command))
  clearline()
  return commands


# Drops the first two path components <problem>/<type>/
def print_name(path):
  return os.path.join(*(path.split(os.path.sep)[2:]))


# testcases; returns list of basenames
def get_testcases(problem, needans=True, only_sample=False):
  infiles = glob(os.path.join(problem, 'data/sample/*.in'))
  if not only_sample:
    infiles += glob(os.path.join(problem, 'data/secret/*.in'))

  print_action('Reading testcases')

  testcases = []
  for f in infiles:
    name = os.path.splitext(f)[0]
    if needans and not os.path.isfile(name + '.ans'):
      continue
    testcases.append(name)
  testcases.sort()
  clearline()

  return testcases


def get_validators(problem, validator_type):
  return build_directory(
      os.path.join(problem, validator_type + '_validators/'),
      action='Building validator')


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
  testcases = get_testcases(problem, validator_type == 'output')
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
  i = 0
  total = len(testcases)
  for testcase in testcases:
    print_action_bar(action, i, total, (
        '{:<' + str(max_testcase_len+1) + '}').format(print_name(testcase) + ext))
    i += 1
    for validator in validators:
      # simple `program < test.in` for input validation and ctd output validation
      if validator_type == 'input' or os.path.splitext(
          validator[0])[1] == '.ctd':
        ret = exec_command(
            validator[1] + flags,
            expect=rtv_ac,
            stdin=open(testcase + ext, 'r'))
      else:
        # more general `program test.in test.ans feedbackdir < test.in/ans` output validation otherwise
        ret = exec_command(
            validator[1] + [testcase + '.in', testcase + '.ans', tmpdir] +
            flags,
            expect=rtv_ac,
            stdin=open(testcase + ext, 'r'))
      if ret[0] is not True:
        success = False

        print_action(
            action, ('{:<' + str(max_testcase_len+1) +
                     '}').format(print_name(testcase) + ext),
            end='')
        print(_c.red, 'FAILED ', validator[0], _c.reset, sep='', end='')

        # Print error message?
        if ret[1] is not None:
          # Print the error on a new line, in orange.
          print('  ', _c.orange, ret[1], _c.reset, sep='', end='', flush=True)
        else:
          print(flush=True)
      else:
        if verbose:
          print()

  if not verbose and success:
    print_action(action, _c.green + 'Done' + _c.reset, end='\n')
  else:
    clearline()
    print()
  return success


# This prints the number belonging to the count.
# This can be a red/white colored number, or Y/N
def get_stat(count, threshold=True, upper_bound=1e10):
  if threshold is True:
    if count >= 1:
      return _c.white + 'Y' + _c.reset
    else:
      return _c.red + 'N' + _c.reset
  return (_c.white if threshold <= count <= upper_bound else
          _c.red) + str(count) + _c.reset


def stats(problems):
  # stats include:
  # #AC, #WA, #TLE, java?, #samples, #secret,
  # domjudge-problem.ini?, solution.tex?

  headers = [
      'problem', 'AC', 'WA', 'TLE', 'java', 'sample', 'secret', 'ini', 'sol'
  ]
  paths = [
      'submissions/accepted/*',
      'submissions/wrong_answer/*',
      'submissions/time_limit_exceeded/*',
      'submissions/accepted/*.java',
      'data/sample/*.in',
      'data/secret/*.in',
      'domjudge-problem.ini',
      'problem_statement/solution.tex'
  ]

  cumulative = [0] * len(paths)

  header_string = ''
  format_string = ''
  for header in headers:
    if header == 'problem':
      width = len(header)
      for problem in problems:
        width = max(width, len(problem))
      header_string += '{:<' + str(width) + '}'
      format_string += '{:<' + str(width) + '}'
    else:
      width = len(header)
      header_string += ' {:>' + str(width) + '}'
      format_string += ' {:>' + str(width + len(_c.white) + len(_c.reset)) + '}'
  header_string = _c.bold + header_string + _c.reset

  print(header_string.format(*headers))

  for problem in problems:
    counts = [len(glob(os.path.join(problem, x))) for x in paths]
    for i in range(0, len(paths)):
      cumulative[i] = cumulative[i] + counts[i]
    print(
        format_string.format(
            problem,
            get_stat(counts[0], 3),
            get_stat(counts[1], 2),
            get_stat(counts[2], 1),
            get_stat(counts[3]),
            get_stat(counts[4], 2),
            get_stat(counts[5], 15, 50),
            get_stat(counts[6]),
            get_stat(counts[7])))

  # print the cumulative count
  print('-' * 80)
  print(format_string.format(*(
      ['TOTAL'] + list(map(lambda x: get_stat(x, False), cumulative)))))


# returns a map {answer type -> [(name, command)]}
def get_submissions(problem):
  dirs = glob(os.path.join(problem, 'submissions/*/'))
  commands = {}
  for d in dirs:
    dirname = os.path.basename(os.path.normpath(d))
    if not dirname.upper() in problem_outcomes:
      continue
    # include directory in submission name
    commands[dirname.upper()] = build_directory(d, True, 'Build submission')
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
    words1 = re.split(rb' +', data1)
    words2 = re.split(rb' +', data2)
    if words1[-1] == '':
      words1.pop()
    if words2[-1] == '':
      words2.pop()
    if words1[0] == '':
      words1.pop(0)
    if words2[0] == '':
      words2.pop(0)

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

  peakerr = 0
  for (w1, w2) in zip(words1, words2):
    if w1 != w2:
      try:
        f1 = float(w1)
        f2 = float(w2)
        err = abs(f1 - f2)
        peakerr = max(peakerr, err)
        if ((settings.floatabs is None or err > settings.floatabs) and
            (settings.floatrel is None or err > settings.floatrel * f1)):
          return (False, quick_diff(data1, data2))
      except ValueError:
        return (False, quick_diff(data1, data2))

  return (True, 'float: ' + str(peakerr))


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
          output_validator[1] + [testcase + '.in', testcase + '.ans', tmpdir] +
          flags,
          expect=rtv_ac,
          stdin=outf)
    if ret[0] is True:
      continue
    if ret[0] == rtv_wa:
      return (False, ret[1])
    print('ERROR in output validator ', output_validator[0], ' exit code ',
          ret[0], ': ', ret[1])
    exit(False)
  return (True, '')


# Return (ret, timeout (True/False), duration)
def run_testcase(run_command, testcase, outfile, tle=None):
  timeout = False
  with open(testcase + '.in', 'rb') as inf:
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
            timeout=float(args.timeout) if hasattr(args, 'timeout') and args.timeout else 2 * tle)
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
      val_ret = default_output_validator(testcase + '.ans', outfile, settings)
    elif settings.validation == 'custom':
      val_ret = custom_output_validator(testcase, outfile, settings,
                                    output_validators)
    else:
      print(_c.red + 'Validation type must be one of `default` or `custom`' +
              _c.reset)
      exit()
    verdict = 'ACCEPTED' if val_ret[0] else 'WRONG_ANSWER'
    remark = val_ret[1]

    if verdict == 'WRONG_ANSWER' and args.output and run_ret[1] is not None:
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

  need_newline = verbose == 1

  verdict_count = {}
  for outcome in problem_outcomes:
    verdict_count[outcome] = 0
  time_total = 0
  time_max = 0

  action = 'Running ' + submission[0]
  max_testcase_len = max([len(print_name(testcase)) for testcase in testcases])
  i = 0
  total = len(testcases)

  printed_error = False

  for testcase in testcases:
    print_action_bar(
        action, i, total,
        ('{:<' + str(max_testcase_len + max_submission_len - len(submission[0]))
         + '}').format(print_name(testcase)))
    i += 1

    outfile = os.path.join(tmpdir, 'test.out')
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
    if verbose or not got_expected:
      printed_error = True
      print_action(
          action, ('{:<' + str(max_testcase_len) + '}').format(
              print_name(testcase)),
          end='')
      color = _c.green if got_expected else _c.red
      print(
          ' ' * (1 + max_submission_len - len(submission[0])),
          '{:6.3f}s'.format(runtime),
          ' ',
          color,
          verdict,
          _c.reset,
          sep='',
          end='')

      # Print error message?
      if remark:
        # Print the error on a new line, in orange.
        print(
            '  ',
            _c.orange,
            add_newline(remark),
            _c.reset,
            sep='',
            end='',
            flush=True)
      else:
        print(flush=True)

    if not verbose and verdict in ['TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR']:
      break

  verdict = 'ACCEPTED'
  for v in reversed(problem_outcomes):
    if verdict_count[v] > 0:
      verdict = v
      break

  if printed_error:
    color = _c.boldgreen if verdict == expected else _c.boldred
  else:
    color = _c.green if verdict == expected else _c.red

  clearline()
  print_action(
      _c.white + action + _c.reset,
      ' ' * (max_submission_len - len(submission[0]) + max_testcase_len - 15) +
      (_c.bold if printed_error else '') + 'max/sum {:6.3f}s {:6.3f}s '.format(
          time_max, time_total) + color + verdict + _c.reset,
      end='\n')

  if verbose or printed_error:
    print()

  return verdict == expected


def get_submission_type(s):
  ls = s.lower()
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
  if settings.testcases:
    testcases = [os.path.join(problem, t) for t in settings.testcases]
  else:
    testcases = get_testcases(problem, True)

  output_validators = None
  if settings.validation == 'custom':
    output_validators = get_validators(problem, 'output')

  if settings.submissions:
    submissions = {
        'ACCEPTED': [],
        'WRONG_ANSWER': [],
        'TIME_LIMIT_EXCEEDED': [],
        'RUN_TIME_ERROR': []
    }
    for submission in settings.submissions:
      path = os.path.join(problem, submission)
      run_command = build(path, action='Build submission')
      if run_command:
        submissions[get_submission_type(path)].append((print_name(path),
                                                       run_command))
  else:
    submissions = get_submissions(problem)

  max_submission_len = max(
      [len(x[0]) for cat in submissions for x in submissions[cat]])

  success = True
  verdict_table = []
  for verdict in problem_outcomes:
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
    # Begin by aggregating bitstrings for all testcases, and find bitstrings occurring often (>=TABLE_THRESHOLD).
    single_verdict = lambda row, testcase: str(int(row[testcase])) if testcase in row else '-'
    make_verdict = lambda tc: ''.join(map(lambda row: single_verdict(row, testcase), verdict_table))
    resultant_count, resultant_id = dict(), dict()
    special_id = 0
    for testcase in testcases:
      resultant = make_verdict(testcase)
      if resultant not in resultant_count:
        resultant_count[resultant] = 0
      resultant_count[resultant] += 1
      if resultant_count[resultant] == TABLE_THRESHOLD:
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
    submission = os.path.join(problem, settings.submission)
  else:
    # only get one accepted submission
    submissions = glob(os.path.join(problem, 'submissions/accepted/*'))
    if len(submissions) == 0:
      print('No submission found for this problem!')
      exit()
    submissions.sort()
    # Look fora c++ solution if available.
    submission = None
    for s in submissions:
      if os.path.splitext(s)[1] == '.cpp':
        submission = s
        break
      else:
        if submission is None:
          submission = s

  print('Using', print_name(submission))

  # build submission
  run_command = build(submission)

  # get all testcases with .in files
  testcases = get_testcases(problem, False)

  nsame = 0
  nchange = 0
  nskip = 0
  nnew = 0
  nfail = 0

  max_testcase_len = max([len(print_name(testcase)) for testcase in testcases])
  i = 0
  total = len(testcases)

  for testcase in testcases:
    print_action_bar('Generate', i, total,
                     ('{:<' + str(max_testcase_len) + '}').format(
                         print_name(testcase)))
    i += 1

    outfile = os.path.join(tmpdir, 'test.out')
    try:
      os.unlink(outfile)
    except OSError:
      pass
    ret, timeout, duration = run_testcase(run_command, testcase, outfile,
                                          settings.timelimit)
    message = ''
    force = False
    if ret[0] is not True or timeout is True:
      message = 'FAILED'
      force = True
      nfail += 1
    else:
      if os.access(testcase + '.ans', os.R_OK):
        compare_settings = argparse.Namespace()
        compare_settings.__dict__.update({
            'case_sensitive': False,
            'space_change_sensitive': False,
            'floatabs': None,
            'floatrel': None
        })
        if default_output_validator(testcase + '.ans', outfile,
                                    compare_settings)[0]:
          nsame += 1
        else:
          if hasattr(settings, 'force') and settings.force:
            shutil.move(outfile, testcase + '.ans')
            nchange += 1
            message = 'CHANGED'
            force = True
          else:
            nskip += 1
            message = _c.red + 'SKIPPED' + _c.reset + '; supply -f to overwrite'
            force = True
      else:
        shutil.move(outfile, testcase + '.ans')
        nnew += 1
        message = 'NEW'
        force = True

    if verbose or force:
      print_action(
          'Generate', ('{:<' + str(max_testcase_len) + '}').format(
              print_name(testcase)) + '  ' + message,
          end='\n')

  clearline()
  print()
  print('Done:')
  print('%d testcases new' % nnew)
  print('%d testcases changed' % nchange)
  print('%d testcases skipped' % nskip)
  print('%d testcases unchanged' % nsame)
  print('%d testcases failed' % nfail)


# https://stackoverflow.com/questions/16259923/how-can-i-escape-latex-special-characters-inside-django-templates
def tex_escape(text):
  """
        :param text: a plain text message
        :return: the message escaped to appear correctly in LaTeX
    """
  conv = {
      '&': r'\&',
      '%': r'\%',
      '$': r'\$',
      '#': r'\#',
      #        '_': r'\_',
      # For monospaced purpose, use instead:
      '_': r'\char`_',
      '{': r'\{',
      '}': r'\}',
      '~': r'\textasciitilde{}',
      '^': r'\^{}',
      #        '\\': r'\textbackslash{}',
      # For monospaced purpose, use instead:
      '\\': r'\char`\\',
      '<': r'\textless{}',
      '>': r'\textgreater{}',
      '\'': r'\textquotesingle{}',
  }
  regex = re.compile('|'.join(
      re.escape(str(key))
      for key in sorted(conv.keys(), key=lambda item: -len(item))))
  text = regex.sub(lambda match: conv[match.group()], text)
  # Escape leading spaces separately
  regex = re.compile('^ ')
  text = regex.sub('\\\\phantom{.}', text)
  return text


def require_latex_build_dir():
  # Set up the build directory if it does not yet exist.
  builddir = os.path.normpath(os.path.join(TOOLS_ROOT, 'latex/build'))
  if not os.path.isdir(builddir):
    if os.path.islink(builddir):
      os.unlink(builddir)
    tmpdir = tempfile.mkdtemp(prefix='bapctools_latex')
    os.symlink(tmpdir, builddir)
  return builddir


# Build a pdf for the problem. Explanation in latex/README.md
def build_problem_pdf(problem, make_pdf=True):
  builddir = require_latex_build_dir()

  # Make the build/<problem> directory
  os.makedirs(os.path.join(builddir, problem), exist_ok=True)
  # build/problem -> build/<problem>
  problemdir = os.path.join(builddir, 'problem')
  if os.path.exists(problemdir):
    os.unlink(problemdir)
  os.symlink(problem, problemdir)
  # link problem_statement dir
  statement_target = os.path.join(builddir, 'problem/problem_statement')
  if not os.path.exists(statement_target):
    if os.path.islink(statement_target):
      os.unlink(statement_target)
    os.symlink(
        os.path.abspath(os.path.join(problem, 'problem_statement')),
        statement_target)

  # create the problemid.tex file which sets the section counter
  problemid_file_path = os.path.join(builddir, 'problem/problemid.tex')
  with open(problemid_file_path, 'wt') as problemid_file:
    config = read_configs(problem)
    problemid = ord(config['probid']) - ord('A')
    problemid_file.write('\\setcounter{section}{' + str(problemid) + '}')
    # Also renew the timelimit command. Use an integral timelimit if
    # possible
    tl = config['timelimit']
    tl = int(tl) if abs(tl - int(tl)) < 0.25 else tl
    renewcom = '\\renewcommand{\\timelimit}{' + str(tl) + '}'
    problemid_file.write(renewcom)

  # create the samples.tex file
  samples = get_testcases(problem, needans=True, only_sample=True)
  samples_file_path = os.path.join(builddir, 'problem/samples.tex')
  with open(samples_file_path, 'wt') as samples_file:
    for sample in samples:
      samples_file.write('\\begin{Sample}\n')

      with open(sample + '.in', 'rt') as in_file:
        lines = []
        for line in in_file:
          lines.append(tex_escape(line))
        samples_file.write('\\newline\n'.join(lines))

      # Separate the left and the right column.
      samples_file.write('&\n')

      with open(sample + '.ans', 'rt') as ans_file:
        lines = []
        for line in ans_file:
          lines.append(tex_escape(line))
        samples_file.write('\\newline\n'.join(lines))

      # We must include a \\ in latex at the end of the table row.
      samples_file.write('\\\\\n\\end{Sample}\n')

  if not make_pdf:
    return True

  # run pdflatex
  pwd = os.getcwd()
  os.chdir(os.path.join(TOOLS_ROOT, 'latex'))
  subprocess.call(
      ['pdflatex', '-output-directory', './build/problem', 'problem.tex'])
  os.chdir(pwd)

  # link the output pdf
  pdf_path = os.path.join(problem, 'problem.pdf')
  if not os.path.exists(pdf_path):
    os.symlink(os.path.join(builddir, pdf_path), pdf_path)

  return True


# Build a pdf for an entire problemset. Explanation in latex/README.md
def build_contest_pdf(contest, problems, solutions=False, web=False):
  builddir = require_latex_build_dir()

  statement = not solutions

  # Make the build/<contest> directory
  os.makedirs(os.path.join(builddir, contest), exist_ok=True)
  # build/contest -> build/<contest>
  contest_dir = os.path.join(builddir, 'contest')
  if os.path.exists(contest_dir):
    os.unlink(contest_dir)
  os.symlink(contest, contest_dir)
  # link contest.tex
  config_target = os.path.join(builddir, 'contest/contest.tex')
  if not os.path.exists(config_target):
    if os.path.islink(config_target):
      os.unlink(config_target)
    os.symlink(os.path.abspath('contest.tex'), config_target)

  # link solution_stats
  stats = os.path.abspath('solution_stats.tex')
  if solutions and os.path.exists(stats):
    stats_target = os.path.join(builddir, 'contest/solution_stats.tex')
    if not os.path.exists(stats_target):
      if os.path.islink(stats_target):
        os.unlink(stats_target)
      os.symlink(stats, stats_target)

  # Create the contest/problems.tex file.
  t = 'solution' if solutions else 'problem'
  problems_path = os.path.join(builddir, 'contest', t + 's.tex')
  problems_with_ids = sort_problems(problems)
  with open(problems_path, 'wt') as problems_file:
    for problem_with_id in problems_with_ids:
      problem = problem_with_id[0]
      includedir = os.path.join('.', 'build', problem, 'problem_statement')
      includepath = os.path.join(includedir, t + '.tex')
      if os.path.exists(os.path.join(TOOLS_ROOT, 'latex', includepath)):
        problems_file.write('\\begingroup\\graphicspath{{' +
                            os.path.join(includedir,'') +
                            '}}\n')
        problems_file.write('\\input{' + os.path.join('.','build',problem, 'problemid.tex') + '}\n')
        problems_file.write('\\input{' + includepath + '}\n')
        if statement:
          problems_file.write('\\input{' + os.path.join('.', 'build', problem,
                                                        'samples.tex') + '}\n')
        problems_file.write('\\endgroup\n')

    # include a statistics slide in the solutions PDF
    if solutions and os.path.exists(stats):
        problems_file.write('\\input{' + os.path.join('.', 'build', 'contest', 'solution_stats.tex') + '}\n')

  # Link logo. Either `contest/../logo.png` or `images/logo-not-found.png`
  logo_path = os.path.join(builddir, 'contest/logo.pdf')
  if not os.path.exists(logo_path):
    if os.path.exists('../logo.pdf'):
      os.symlink(os.path.abspath('../logo.pdf'), logo_path)
    else:
      os.symlink(
          os.path.abspath(
              os.path.join(TOOLS_ROOT, 'latex/images/logo-not-found.pdf')),
          logo_path)

  # Run pdflatex for problems
  pwd = os.getcwd()
  os.chdir(os.path.join(TOOLS_ROOT, 'latex'))
  f = 'solutions' if solutions else ('contest-web' if web else 'contest')
  # The absolute path is needed, because otherwise the `contest.tex` file
  # in the output directory will get priority.
  if subprocess.call([
      'pdflatex', '-output-directory', './build/contest',
      os.path.abspath(f + '.tex')
  ]) != 0:
    # Non-zero exit code marks a failure.
    print(_c.red, 'An error occurred while compiling latex!', _c.reset)
    return False
  os.chdir(pwd)

  # link the output pdf
  if not os.path.exists(f + '.pdf'):
    os.symlink(os.path.join(builddir, contest, f + '.pdf'), f + '.pdf')

  return True


# sort problems by the id in domjudge-problem.ini
# return [(problem, id)]
def sort_problems(problems):
  configs = [ (problem, read_configs(problem)) for problem in problems ]
  problems = [(pair[0], pair[1]['probid']) for pair in configs if 'probid' in pair[1] ]
  problems.sort(key=lambda x: x[1])
  return problems


def print_sorted(problems, args):
  prefix = args.contest + '/' if args.contest else ''
  for problem in sort_problems(problems):
    print(prefix + problem[0])

"""
DISCLAIMER:
  This tool was only made to check constraints faster.
  However it is not guaranteed it will find all constraints.
  Checking constraints by yourself is probably the best way.
"""
def check_constraints(problem, settings):
  vinput = os.path.join(problem, 'input_validators/input_validator.cpp')
  voutput = os.path.join(problem, 'output_validators/output_validator.cpp')

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

  statement = os.path.join(problem, 'problem_statement/problem.tex')
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
def alpha_num(string):
  return re.sub(r'[^a-z0-9]', '', string.lower())


# Creates a symlink if it not exists, else it does nothing
# the symlink will be created at link_name, pointing to target
def symlink_quiet(target, link_name):
  if os.path.islink(link_name):
    os.unlink(link_name)
  if not os.path.exists(link_name):
    os.symlink(target, link_name)
  # if it existed and is not a symlink, do nothing


# preparing a kattis directory involves creating lots of symlinks to files which
# are the same. If it gets changed for the format, we copy the file and modify
# it accordingly.
def prepare_kattis_directory():
  if not os.path.exists('kattis'):
    os.mkdir('kattis')


def prepare_kattis_problem(problem, settings):
  shortname = alpha_num(os.path.basename(os.path.normpath(problem)))
  path = os.path.join('kattis', shortname)
  orig_path = os.path.join('../../', problem)

  if not os.path.exists(path):
    os.mkdir(path)

  for same in [ 'data', 'generators', 'problem.yaml', 'submissions' ]:
    symlink_quiet(os.path.join(orig_path, same), os.path.join(path, same))

  # make an input validator
  vinput = os.path.join(path, 'input_format_validators')
  if not os.path.exists(vinput):
    os.mkdir(vinput)

  symlink_quiet(
      os.path.join('../', orig_path, 'input_validators'),
      os.path.join(vinput, shortname + '_validator'))

  # After this we only look inside directories.
  orig_path = os.path.join('../', orig_path)

  # make a output_validators directory with in it "$shortname-validator"
  if settings.validation == 'custom':
    voutput = os.path.join(path, 'output_validators')
    if not os.path.exists(voutput):
      os.mkdir(voutput)
    symlink_quiet(
        os.path.join(orig_path, 'output_validators'),
        os.path.join(voutput, shortname + '_validator'))

  # make a problem statement with problem.en.tex -> problem.tex,
  # but all other files intact.
  pst = 'problem_statement'
  st = os.path.join(path, pst)
  if not os.path.exists(st):
    os.mkdir(st)

  # determine the files in the 'problem statement' directory
  wd = os.getcwd()
  os.chdir(os.path.join(problem, pst))
  files = glob('*')
  os.chdir(wd)

  assert "problem.tex" in files

  # remember: current wd is st
  for f in files:
    if f != "problem.tex":
      symlink_quiet(os.path.join(orig_path, pst, f), os.path.join(st, f))

  source = os.path.join(problem, pst, 'problem.tex')
  target = os.path.join(st, 'problem.en.tex')
  if os.path.islink(target) or os.path.exists(target):
    os.unlink(target)
  with open(source, 'r') as f, open(target, 'w') as g:
    for line in f:
      if line == "\\begin{Input}\n":
        g.write("\section*{Input}\n")
      elif line == "\\begin{Output}\n":
        g.write("\section*{Output}\n")
      elif line in [ "\\end{Input}\n", "\\end{Output}\n" ]:
        g.write("\n")
      else:
        g.write(line)


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


def main():
  global TOOLS_ROOT
  executable = __file__
  if os.path.islink(executable):
    executable = os.path.realpath(executable)
  TOOLS_ROOT = os.path.realpath(
      os.path.normpath(os.path.join(os.path.dirname(executable), '..')))

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
      aliases=['new-contest', 'create-contest', 'add-contest'],
      parents=[global_parser],
      help='Add a new contest to the current directory.')
  contestparser.add_argument(
      'contestname', help='The name of the contest, [a-z0-9]+.')

  # New problem
  problemparser = subparsers.add_parser(
      'problem',
      aliases=['new-problem', 'create-problem', 'add-problem'],
      parents=[global_parser],
      help='Add a new problem to the current directory.')
  problemparser.add_argument(
      'problemname', help='The name of the problem, [a-z0-9]+.')

  # Problem statements
  pdfparser = subparsers.add_parser(
      'pdf',
      aliases=['build', 'statement'],
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
      aliases=['sol', 'slides'],
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
      aliases=['grammar'],
      parents=[global_parser],
      help='validate all grammar')
  subparsers.add_parser(
      'input',
      aliases=['in'],
      parents=[global_parser],
      help='validate input grammar')
  subparsers.add_parser(
      'output',
      aliases=['out'],
      parents=[global_parser],
      help='validate output grammar')
  subparsers.add_parser(
      'constraints',
      aliases=['con', 'bounds'],
      parents=[global_parser],
      help='prints all the constraints found in problemset and validators')

  # Stats
  subparsers.add_parser(
      'stats',
      aliases=['stat', 'status'],
      parents=[global_parser],
      help='show statistics for contest/problem')

  # Generate
  genparser = subparsers.add_parser(
      'generate',
      aliases=['gen'],
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

  # Build a directory for verification with the kattis format
  subparsers.add_parser(
      'kattis',
      parents=[global_parser],
      help='Build a directory for verification with the kattis format')

  # Process arguments
  global args
  args = parser.parse_args()
  global verbose
  verbose = args.verbose if args.verbose else 0
  action = args.action

  if action in ['contest', 'new-contest', 'create-contest', 'add-contest']:
    shutil.copytree(
        os.path.join(TOOLS_ROOT, 'skel/contest'),
        args.contestname,
        symlinks=True)
    exit()

  if action in ['problem', 'new-problem', 'create-problem', 'add-problem']:
    shutil.copytree(
        os.path.join(TOOLS_ROOT, 'skel/problem'),
        args.problemname,
        symlinks=True)
    exit()

  # Get problems and cd to contest
  problems, level, contest = get_problems(args.contest)

  if action in ['generate', 'gen']:
    if level != 'problem':
      print('Generating output files only works for a single problem.')
      exit()

  if action == 'run':
    if args.submissions:
      if level != 'problem':
        print('Running a given submission only works from a problem directory.')
        exit()
      (args.submissions, args.testcases) = split_submissions(args.submissions)
    else:
      args.testcases = []

  if action in ['stats', 'status', 'stat']:
    stats(problems)
    return
  if action == 'sort':
    print_sorted(problems, args)
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
    problemsettings = read_configs(problem)
    settings = args
    for key in problemsettings:
      vars(settings)[key] = problemsettings[key]

    if action in ['pdf', 'build', 'statement', 'sol', 'slides', 'solutions']:
      # only build the pdf on the problem level
      success &= build_problem_pdf(problem, args.all or level == 'problem')

    if action in ['validate', 'grammar', 'input', 'in', 'all']:
      success &= validate(problem, 'input', settings)
    if action in ['generate', 'gen', 'all']:
      generate_output(problem, settings)
    if action in ['validate', 'grammar', 'output', 'out', 'all']:
      success &= validate(problem, 'output', settings)
    if action in ['run', 'all']:
      success &= run_submissions(problem, settings)
    if action in ['constraints', 'bounds', 'con']:
      success &= check_constraints(problem, settings)
    if action in ['zip']:
      output = alpha_num(os.path.basename(os.path.normpath(problem))) + '.zip'
      problem_zips.append(output)
      if not args.skip:
        success &= build_problem_pdf(problem, True)
        if not args.force:
          success &= validate(problem, 'input', settings)
          success &= validate(problem, 'output', settings)

        # Write to problemname.zip, where we strip all non-alphanumeric from the
        # problem directory name.
        success &= build_problem_zip(problem, output, settings)
    if action == 'kattis':
      prepare_kattis_problem(problem, settings)

    if len(problems) > 1:
      print()

  # build pdf for the entire contest
  if action in ['pdf', 'build', 'statement'] and level == 'contest':
    # Run 3 times, to fix the TOC.
    success &= build_contest_pdf(contest, problems, web=args.web)
    success &= build_contest_pdf(contest, problems, web=args.web)
    success &= build_contest_pdf(contest, problems, web=args.web)

  if action in ['sol', 'solutions', 'slides'] and level == 'contest':
    success &= build_contest_pdf(contest, problems, solutions=True)

  if action in ['zip'] and args.contest:
    success &= build_contest_pdf(contest, problems)
    success &= build_contest_pdf(contest, problems)
    success &= build_contest_pdf(contest, problems)
    success &= build_contest_pdf(contest, problems, web=True)
    success &= build_contest_pdf(contest, problems, solutions=True)

    build_contest_zip(problem_zips, contest + '.zip', args)

  if not success:
    exit()

if __name__ == '__main__':
  main()
shutil.rmtree(tmpdir)

# vim: et ts=2 sts=2 sw=2:
