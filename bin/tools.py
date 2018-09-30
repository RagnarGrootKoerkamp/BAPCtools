#!/usr/bin/python3

"""
Can be run on multiple levels:
    - from the root of the git repository
    - from a contest directory
    - from a problem directory
the tool will know where it is (by looking for the .git directory) and run on everything inside it

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
problem_outcomes = ['ACCEPTED', 'WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED','RUN_TIME_ERROR']
tmpdir = tempfile.mkdtemp(prefix='bapctools_')

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD = 4

TOOLS_ROOT = ''

# this is lifted for convenience
args = None
verbose = 0

# color printing
class Colorcodes(object):
    def __init__(self):
        self.bold = '\033[;1m'
        self.reset = '\033[0;0m'
        self.blue = '\033[;34m'
        self.green = '\033[;32m'
        self.orange = '\033[;33m'
        self.red = '\033[;31m'
        self.white = '\033[;39m'
_c = Colorcodes()

def exit(clean = True):
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
        print("ERROR: Can't determine git root directory; run this from problem, contest, or root")
        exit()

    # return list of problems in contest directory
    return ([os.path.normpath(p[0]) for p in sort_problems(glob('*/'))], 'contest', os.path.basename(os.getcwd()))

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
    yamlpath = os.path.join(problem,'problem.yaml')
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
        while i < len(flags) :
            if flags[i] in ['case_sensitive', 'space_change_sensitive']:
                settings[flags[i]] = True
            elif flags[i] == 'float_absolute_tolerance':
                settings['floatabs'] = float(flags[i+1])
                i += 1
            elif flags[i] == 'float_relative_tolerance':
                settings['floatrel'] = float(flags[i+1])
                i += 1
            elif flags[i] == 'float_tolerance':
                settings['floatabs'] = float(flags[i+1])
                settings['floatrel'] = float(flags[i+1])
                i += 1
            i += 1

    # parse domjudge-problem.ini
    if os.path.isfile(os.path.join(problem,'domjudge-problem.ini')):
        with open(os.path.join(problem,'domjudge-problem.ini')) as f:
            for line in f.readlines():
                key, var = line.strip().split('=')
                var = var[1:-1]
                settings[key] = float(var) if key  == 'timelimit' else var

    return settings

# is file at path executable
def is_executable(path):
    return os.path.exists(path) and (os.stat(path).st_mode & (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH))

# run a command with the required verbosity
def exec_command(command, **kwargs):
    if verbose == 3:
        print()
        if 'stdin' in kwargs:
            print(command, '<', kwargs.get('stdin').name)
        else:
            print(command)
        return subprocess.call(command, **kwargs)
    else:
        if 'stdout' in kwargs:
            return subprocess.call(command, stderr=open(os.devnull, 'w'), **kwargs)
        else:
            return subprocess.call(command, stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT, **kwargs)

# a function to convert c++ or java to something executable
# returns a command to execute
def build(path):
    # mirror directory structure on tmpfs
    basename = os.path.basename(path)
    (base, ext) = os.path.splitext(basename)
    exefile = os.path.join(tmpdir,os.path.dirname(path),base)
    os.makedirs(os.path.dirname(exefile), exist_ok=True)
    if ext == '.c':
        compile_command = [ 'gcc', '-std=c11', '-Wall', '-O2',
                            '-o', exefile, path, '-lm' ]
        run_command = [ exefile ]
    elif ext in ('.cc', '.cpp'):
        compile_command = [ 'g++', '-std=c++11', '-Wall', '-O2',
                            '-o', exefile, path ]
        run_command = [ exefile ]
    elif ext == '.java':
        compile_command = [ 'javac', '-d', tmpdir, path ]
        run_command = [ 'java', '-enableassertions', '-Xss1532M',
                        '-cp', tmpdir, base ]
    elif ext in ('.py', '.py2'):
        compile_command = None
        run_command = [ 'python2', path ]
    elif ext == '.py3':
        compile_command = None
        run_command = [ 'python3', path ]
    elif ext == '.ctd':
        compile_command = None
        run_command = [ os.path.join(TOOLS_ROOT, 'checktestdata', 'checktestdata'), path ]
    else:
        print(path,'has unknown extension',ext)
        exit()

    # prevent building something twice
    if compile_command is not None and not os.path.isfile(exefile):
        ret = exec_command(compile_command)
        if ret:
            print(_c.red,'Failed to build ',compile_command, ': Exited with code ', ret, _c.reset,flush=True)
            return None
    return run_command

# build all files in a directory; return a list of tuples (file, command)
# When 'build' is found, we execute it, and return 'run' as the executable
def build_directory(directory, include_dirname=False):
    commands = []

    buildfile = os.path.join(directory,'build')
    runfile = os.path.join(directory,'run')

    if is_executable(buildfile):
        cur_path = os.getcwd()
        os.chdir(directory)
        if exec_command(['./build']):
            print(path, 'failed!')
            exit()
        os.chdir(cur_path)
        if not is_executable(runfile):
            print('after running',path,',', funfile,'must be a valid executable!')
            exit()
        return [('run',[runfile])]

    if is_executable(runfile):
        return [('run',[runfile])]


    files = glob(os.path.join(directory,'*'))
    files.sort()
    for path in files:
        basename = os.path.basename(path)
        if basename == 'a.out':
            continue

        if include_dirname:
            dirname = os.path.basename(os.path.dirname(path))
            name = os.path.join(dirname,basename)
        else:
            name = basename

        if is_executable(path):
            commands.append((name, [path]))
        else:
            ext = os.path.splitext(name)[1]
            if ext in build_extensions:
                # None on compiler failure
                run_command = build(path)
                if run_command != None:
                    commands.append((name, run_command))
    return commands

# testcases; returns list of basenames
def get_testcases(problem, needans = True, only_sample = False):
    infiles = glob(os.path.join(problem,'data/sample/*.in'))
    if not only_sample:
        infiles += glob(os.path.join(problem,'data/secret/*.in'))

    testcases = []
    for f in infiles:
        name = os.path.splitext(f)[0]
        if needans and not os.path.isfile(name+'.ans'):
            continue
        testcases.append(name)
    testcases.sort()
    return testcases

# drop a/b/c from a/b/c/{sample,secret}/test
def print_testcase(path):
    name = os.path.basename(path)
    dirname = os.path.basename(os.path.dirname(path))
    return os.path.join(dirname,name)

def get_validators(problem, validator_type):
    return build_directory(os.path.join(problem, validator_type+'_validators/'))

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

    if verbose:
        print(_c.bold, ' Validating', validator_type, _c.reset)

    validators = get_validators(problem, validator_type)
    # validate testcases without answer files
    testcases = get_testcases(problem, True)
    ext = '.in' if validator_type == 'input' else '.ans'

    if len(validators) == 0: return False
    if len(testcases) == 0: return True

    success = True

    # Flags are only needed for output validators; input validators are
    # sensitive by default.
    flags = []
    if validator_type == 'output':
        flags = ['case_sensitive', 'space_change_sensitive']

    # validate the testcases
    for testcase in testcases:
        if verbose:
            print('{:<50}'.format(print_testcase(testcase)+ext),end='')
        failcount = 0
        for validator in validators:
            # simple `program < test.in` for input validation and ctd output validation
            if validator_type == 'input' or os.path.splitext(validator[0])[1] == '.ctd':
                ret = exec_command(validator[1] + flags,
                        stdin=open(testcase+ext,'r'))
            else:
                # more general `program test.in test.ans feedbackdir < test.in/ans` output validation otherwise
                ret = exec_command(validator[1] + [testcase+'.in', testcase+'.ans', tmpdir] + flags,
                        stdin=open(testcase+ext,'r'))
            if ret == rtv_ac:
                pass
            else:
                success = False
                if not verbose and failcount == 0:
                    print('{:<50}'.format(print_testcase(testcase)+ext),end='')
                if failcount == 0:
                    print(_c.bold, end='')
                    print(_c.red, end='')
                    print('FAILED', validator[0], end='',flush=True)
                else:
                    print(',', validator[0], end='',flush=True)
                failcount += 1
        if verbose or failcount>0:
            print(_c.reset)
    return success

# stats
# print(stats_format.format('problem', 'AC', 'WA', 'TLE', 'sample', 'secret', 'ini', 'sol'))
def get_stat(path, threshold = True, upper_bound = 1e10):
    count = len(glob(path))
    if threshold is True:
        if count >= 1:
            return _c.white + 'Y' +  _c.reset
        else:
            return _c.red + 'N' +  _c.reset
    return (_c.white if threshold <= count <= upper_bound else _c.red) + str(count) + _c.reset

def stats(problems):
    # stats include:
    # #AC, #WA, #TLE, java?, #samples, #secret,
    # domjudge-problem.ini?, solution.tex?

    headers = ['problem', 'AC', 'WA', 'TLE', 'java', 'sample', 'secret', 'ini', 'sol']
    header_string = ''
    format_string = ''
    for header in headers:
        if header == 'problem':
            width = len(header)
            for problem in problems:
                width = max(width, len(problem))
            header_string += '{:<'+str(width)+'}'
            format_string += '{:<'+str(width)+'}'
        else:
            width = len(header)
            header_string += ' {:>'+str(width)+'}'
            format_string += ' {:>'+str(width+len(_c.white)+len(_c.reset))+'}'
    header_string = _c.bold + header_string + _c.reset

    print(header_string.format(*headers))

    for problem in problems:
        print(format_string.format(problem,
            get_stat(os.path.join(problem,'submissions/accepted/*', 3)),
            get_stat(os.path.join(problem,'submissions/wrong_answer/*', 2)),
            get_stat(os.path.join(problem,'submissions/time_limit_exceeded/*', 1)),
            get_stat(os.path.join(problem,'submissions/accepted/*.java')),
            get_stat(os.path.join(problem,'data/sample/*.in', 2)),
            get_stat(os.path.join(problem,'data/secret/*.in', 15, 50)),
            get_stat(os.path.join(problem,'domjudge-problem.ini')),
            get_stat(os.path.join(problem,'problem_statement/solution.tex'))
            ))

# returns a map {answer type -> [(name, command)]}
def get_submissions(problem):
    dirs = glob(os.path.join(problem,'submissions/*/'))
    commands = {}
    for d in dirs:
        dirname = os.path.basename(os.path.normpath(d))
        if not dirname.upper() in problem_outcomes:
            continue
        # include directory in submission name
        commands[dirname.upper()] = build_directory(d, True)
    return commands

# return: (success, remark)
def default_output_validator(ansfile, outfile, settings):
    # settings: floatabs, floatrel, case_sensitive, space_change_sensitive
    with open(ansfile, 'rb') as f:
        data1 = f.read()

    with open(outfile, 'rb') as f:
        data2 = f.read()

    if data1 == data2:
        return (True, 'exact')

    if not settings.case_sensitive:
        # convert to lowercase...
        data1 = data1.lower()
        data2 = data2.lower()

        if data1 == data2:
            return (True, 'case')

    if settings.space_change_sensitive and settings.floatabs == None and settings.floatrel == None:
        return (False, 'wrong')

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
            print('Strings became equal after space sensitive splitting! Something is wrong!')
            exit()

    if settings.floatabs is None and settings.floatrel is None:
        return (False, 'wrong')

    if len(words1) != len(words2):
        return (False, 'wrong')

    peakerr = 0
    for (w1, w2) in zip(words1, words2):
        if w1 != w2:
            try:
                f1  = float(w1)
                f2  = float(w2)
                err = abs(f1 - f2)
                peakerr = max(peakerr, err)
                if ( (settings.floatabs is None or err > settings.floatabs) and
                     (settings.floatrel is None or err > settings.floatrel * f1) ):
                    return (False, 'wrong')
            except ValueError:
                return (False, 'wrong')

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
        with open(outfile, 'rb') as outf:
            ret = exec_command(output_validator[1] + [testcase+'.in', testcase+'.ans', tmpdir] + flags, stdin=outf)
        if ret == rtv_ac:
            continue
        if ret == rtv_wa:
            return (False, output_validator)
        print('  ERROR in output validator ',output_validator[0], ' exit code ', ret)
        exit(False)
    return (True, '')

def run_testcase(run_command, testcase, outfile, tle=None):
    timeout = False
    with open(testcase+'.in', 'rb') as inf:
        with open(outfile, 'wb') as outf:
            tstart = time.monotonic()
            try:
                # Double the tle to check for solutions close to the required bound
                ret = exec_command(run_command, stdin=inf, stdout=outf, timeout=2*tle)
            except subprocess.TimeoutExpired:
                timeout = True
                ret = 0
            tend = time.monotonic()

    duration = tend - tstart
    if tle and duration > tle:
        timeout = True
    return (ret, timeout, duration)

# return (verdict, time, remark)
# -v: print failed cases
# -vv: print all cases + timing
def process_testcase(run_command, testcase, outfile, settings, output_validators, silent = False, printnewline = False):

    if not silent and verbose == 2:
        print('{:<50}'.format(print_testcase(testcase)), end='', flush=True)

    ret, timeout, duration = run_testcase(run_command, testcase, outfile, settings.timelimit)

    verdict = None
    remark = ''
    if timeout:
        verdict = 'TIME_LIMIT_EXCEEDED'
    elif ret:
        verdict = 'RUN_TIME_ERROR'
    # now check validity of outfile
    else:
        if settings.validation == 'default':
            ret = default_output_validator(testcase+'.ans', outfile, settings)
        elif settings.validation == 'custom':
            ret = custom_output_validator(testcase, outfile, settings, output_validators)
        else:
            print('Validation type must be one of `default` or `custom`')
            exit()
        verdict = 'ACCEPTED' if ret[0] else 'WRONG_ANSWER'
        remark = ret[1]

    if not verbose or silent: return (verdict, duration)

    if verbose != 2 and verdict != 'ACCEPTED':
        if printnewline:
            print()
        print('{:<50}'.format(print_testcase(testcase)), end='')

    if verbose == 2 or verdict != 'ACCEPTED':
        print('{:6.3f}s'.format(duration),
                _c.red if verdict != 'ACCEPTED' else '',
                verdict,
                _c.reset if verdict != 'ACCEPTED' else '',
                remark, flush=True)

    return (verdict, duration)

# program is of the form (name, command)
# return outcome
# always: failed submissions
# -v: all programs and their results (+failed testcases when expected is 'accepted')
def run_submission(submission, testcases, settings, output_validators, expected='ACCEPTED', table_dict=None):

    if verbose:
        print('{:<50}'.format(submission[0]), end='', flush=True)
    if verbose == 2:
        print()
    need_newline = verbose == 1

    verdict_count = {}
    for outcome in problem_outcomes: verdict_count[outcome] = 0
    time_total = 0
    time_max = 0
    for testcase in testcases:
        outfile = os.path.join(tmpdir, 'test.out')
        #silent = expected != 'ACCEPTED'
        silent = False
        verdict, time = \
            process_testcase(submission[1], testcase, outfile, settings, output_validators,
                    silent, need_newline)
        verdict_count[verdict] += 1
        time_total += time
        time_max = max(time_max, time)

        if table_dict is not None:
            table_dict[testcase] = verdict == 'ACCEPTED'

        if not silent and verdict != 'ACCEPTED':
            need_newline = False

        if hasattr(settings, 'lazy') and settings.lazy and verdict in ['TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR']:
            break

    # default in case of 0 testcases
    verdict = 'ACCEPTED'
    for v in reversed(problem_outcomes):
        if verdict_count[v] > 0:
            verdict = v
            break

    if not verbose and verdict != expected:
        print('{:<50}'.format(submission[0]), end = '')
    if verbose and not need_newline:
        print('{:<50}'.format('-> '+submission[0]), end = '')
    if verbose or verdict != expected:
        print(' m/+ {:6.3f}s {:6.3f}s'.format(time_max, time_total),
                _c.red if verdict != expected else '',
                '{:19}'.format(verdict),
                _c.reset if verdict != expected else '',
                '(expected', expected+')',flush=True)

    return verdict == expected

# return true if all submissions for this problem pass the tests
def run_submissions(problem, settings):
    # Require both in and ans files
    testcases = get_testcases(problem, True)

    output_validators = None
    if settings.validation == 'custom':
        output_validators = get_validators(problem, 'output')

    if hasattr(settings, 'submissions') and settings.submissions:
        commands = []
        for submission in settings.submissions:
            run_command = build(os.path.join(problem, submission))
            if run_command:
                commands.append((os.path.basename(submission), run_command))
        submissions = {'ACCEPTED': commands}
    else:
        submissions = get_submissions(problem)

    if verbose < 2:
        settings.lazy = True

    success = True
    verdict_table = []
    for verdict in problem_outcomes:
        if verdict in submissions:
            for submission in submissions[verdict]:
                verdict_table.append(dict())
                success &= run_submission(submission, testcases, settings,
                        output_validators, verdict, table_dict=verdict_table[-1])

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
        submission = os.path.join(problem,settings.submission)
    else:
        # only get one accepted submission
        submissions = glob(os.path.join(problem,'submissions/accepted/*'))
        if len(submissions) == 0:
            print('No submission found for this problem!')
            exit()
        submissions.sort()
        submission = submissions[0]
        print('Using',print_testcase(submission))

    # build submission
    run_command = build(submission)

    # get all testcases with .in files
    testcases = get_testcases(problem, False)

    nsame = 0
    nchange = 0
    nskip = 0
    nnew = 0
    nfail = 0

    for testcase in testcases:
        if verbose:
            print('{:<50}'.format(testcase), end=' ')
        outfile = os.path.join(tmpdir, 'test.out')
        try:
            os.unlink(outfile)
        except OSError:
            pass
        ret, timeout, duration = run_testcase(run_command, testcase, outfile, settings.timelimit)
        if ret:
            if not verbose:
                print('{:<50}'.format(print_testcase(testcase)), end=' ')
            print('Failure on testcase ', testcase)
            nfail += 1
        else:
            if os.access(testcase+'.ans', os.R_OK):
                compare_settings = argparse.Namespace()
                compare_settings.__dict__.update({
                        'case_sensitive': False,
                        'space_change_sensitive': False,
                        'floatabs': None,
                        'floatrel': None
                    })
                if default_output_validator(testcase+'.ans', outfile, compare_settings)[0]:
                    nsame += 1
                    if verbose:
                        print()
                else:
                    if hasattr(settings, 'force') and settings.force:
                        shutil.move(outfile, testcase+'.ans')
                        nchange += 1
                        if not verbose:
                            print('{:<50}'.format(print_testcase(testcase)), end=' ')
                        print('CHANGED')
                    else:
                        nskip += 1
                        if not verbose:
                            print('{:<50}'.format(print_testcase(testcase)), end=' ')
                        print(_c.red+'SKIPPED'+_c.reset+'; supply -f to overwrite',flush=True)
            else:
                shutil.move(outfile, testcase+'.ans')
                nnew += 1
                if not verbose:
                    print('{:<50}'.format(print_testcase(testcase)), end=' ')
                print('NEW')

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
    }
    regex = re.compile('|'.join(re.escape(str(key)) for key in sorted(conv.keys(), key = lambda item: - len(item))))
    text = regex.sub(lambda match: conv[match.group()], text)
# Escape leading spaces separately
    regex = re.compile('^ ')
    text = regex.sub('\\\\phantom{.}', text)
    return text

def require_latex_build_dir():
    # Set up the build directory if it does not yet exist.
    builddir = os.path.normpath(os.path.join(TOOLS_ROOT,'latex/build'))
    if not os.path.isdir(builddir):
        if os.path.islink(builddir):
            os.unlink(builddir)
        tmpdir = tempfile.mkdtemp(prefix='bapctools_latex')
        os.symlink(tmpdir, builddir)
    return builddir


# Build a pdf for the problem. Explanation in latex/README.md
def build_problem_pdf(problem, make_pdf = True):
    builddir = require_latex_build_dir()

    # Make the build/<problem> directory
    os.makedirs(os.path.join(builddir,problem), exist_ok = True)
    # build/problem -> build/<problem>
    problemdir = os.path.join(builddir,'problem')
    if os.path.exists(problemdir):
        os.unlink(problemdir)
    os.symlink(problem, problemdir)
    # link problem_statement dir
    statement_target = os.path.join(builddir,'problem/problem_statement')
    if not os.path.exists(statement_target):
        if os.path.islink(statement_target):
            os.unlink(statement_target)
        os.symlink(os.path.abspath(os.path.join(problem,'problem_statement')), statement_target)

    # create the problemid.tex file which sets the section counter
    problemid_file_path = os.path.join(builddir,'problem/problemid.tex')
    with open(problemid_file_path, 'wt') as problemid_file:
        config = read_configs(problem)
        print(config)
        problemid = ord(config['probid']) - ord('A')
        problemid_file.write('\\setcounter{section}{' + str(problemid) + '}')

    # create the samples.tex file
    samples = get_testcases(problem, needans = True, only_sample = True)
    samples_file_path = os.path.join(builddir,'problem/samples.tex')
    with open(samples_file_path, 'wt') as samples_file:
        for sample in samples:
            samples_file.write('\\begin{Sample}\n')

            with open(sample+'.in', 'rt') as in_file:
                lines = []
                for line in in_file:
                    lines.append(tex_escape(line))
                samples_file.write('\\newline\n'.join(lines))

            # Separate the left and the right column.
            samples_file.write('&\n')

            with open(sample+'.ans', 'rt') as ans_file:
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
    os.chdir(os.path.join(TOOLS_ROOT,'latex'))
    subprocess.call(['pdflatex', '-output-directory', './build/problem', 'problem.tex'])
    os.chdir(pwd)

    # link the output pdf
    pdf_path = os.path.join(problem, 'problem.pdf')
    if not os.path.exists(pdf_path):
        os.symlink(os.path.join(builddir,pdf_path), pdf_path)

    return True

# Build a pdf for an entire problemset. Explanation in latex/README.md
def build_contest_pdf(contest, problems, solutions=False, web=False):
    builddir = require_latex_build_dir()

    statement = not solutions

    # Make the build/<contest> directory
    os.makedirs(os.path.join(builddir,contest), exist_ok = True)
    # build/contest -> build/<contest>
    contest_dir = os.path.join(builddir, 'contest')
    if os.path.exists(contest_dir):
        os.unlink(contest_dir)
    os.symlink(contest, contest_dir)
    # link contest.tex
    config_target = os.path.join(builddir,'contest/contest.tex')
    if not os.path.exists(config_target):
        if os.path.islink(config_target):
            os.unlink(config_target)
        os.symlink(os.path.abspath('contest.tex'), config_target)

    # Create the contest/problems.tex file.
    t = 'solution' if solutions else 'problem'
    problems_path = os.path.join(builddir,'contest',t+'s.tex')
    problems_with_ids = sort_problems(problems)
    with open(problems_path, 'wt') as problems_file:
        for problem_with_id in problems_with_ids:
            problem = problem_with_id[0]
            includedir  = './build/'+problem+'problem_statement/'
            includepath = includedir + t + '.tex'
            if os.path.exists(TOOLS_ROOT+'/latex/' + includepath):
                problems_file.write('\\begingroup\\graphicspath{{'+includedir+'}}\n')
                problems_file.write('\\input{'+includepath+'}\n')
                if statement:
                    problems_file.write('\\input{./build/'+problem+'samples.tex}\n')
                problems_file.write('\\endgroup\n')

    # Link logo. Either `contest/../logo.png` or `images/logo-not-found.png`
    logo_path = os.path.join(builddir, 'contest/logo.pdf')
    if not os.path.exists(logo_path):
        if os.path.exists('../logo.pdf'):
            os.symlink(os.path.abspath('../logo.pdf'), logo_path)
        else:
            os.symlink(os.path.abspath(os.path.join(TOOLS_ROOT,'latex/images/logo-not-found.pdf')), logo_path)

    # Run pdflatex for problems
    pwd = os.getcwd()
    os.chdir(os.path.join(TOOLS_ROOT,'latex'))
    f = 'solutions' if solutions else ('contest-web' if web else 'contest')
    # The absolute path is needed, because otherwise the `contest.tex` file
    # in the output directory will get priority.
    if subprocess.call(['pdflatex', '-output-directory', './build/contest', os.path.abspath(f+'.tex')]) != 0:
        # Non-zero exit code marks a failure.
        print(_c.red, "An error occurred while compiling latex!", _c.reset)
        return False
    os.chdir(pwd)

    # link the output pdf
    if not os.path.exists(f+'.pdf'):
        os.symlink(builddir+contest+'/'+f+'.pdf', f+'.pdf')

    return True


# sort problems by the id in domjudge-problem.ini
# return [(problem, id)]
def sort_problems(problems):
    problems = [(problem, read_configs(problem)['probid']) for problem in problems]
    problems.sort(key = lambda x: x[1])
    return problems

def print_sorted(problems, args):
    prefix = args.contest + '/' if args.contest else ''
    for problem in sort_problems(problems):
        print(prefix + problem[0])

def check_constraints(problem, settings):
    vinput = os.path.join(problem, 'input_validators/input_validator.cpp')
    voutput = os.path.join(problem, 'output_validators/output_validator.cpp')

    cpp_statement = re.compile('^(const\s+|constexpr\s+)?(int|string|long long|float|double)\s+(\w+)\s*[=]\s*(.*);$')

    defs = []
    for validator in [vinput, voutput]:
        with open(validator) as file:
            for line in file:
                mo = cpp_statement.search(line)
                if mo is not None:
                    defs.append(mo)

    defs_validators = [ (mo.group(3), mo.group(4)) for mo in defs ]

    statement = os.path.join(problem, 'problem_statement/problem.tex')
    latex_define = re.compile('^\\newcommand{\\\\(\w+)}{(.*)}$')
    latex_define = re.compile('{\\\\(\w+)}{(.*)}')

    defs.clear()
    with open(statement) as file:
        for line in file:
            mo = latex_define.search(line)
            if mo is not None:
                defs.append(mo)

    defs_statement = [ (mo.group(1), mo.group(2)) for mo in defs ]

    # print all the definitions.
    nl = len(defs_validators)
    nr = len(defs_statement)

    print('{:^30}|{:^30}'.format('  VALIDATORS', '      PROBLEM STATEMENTS'),sep='')
    for i in range(0, max(nl, nr)):
        if i < nl:
            print('{:>15}  {:<13}'.format(defs_validators[i][1], defs_validators[i][0]),sep='',end='')
        else:
            print('{:^30}'.format(''),sep='',end='')
        print('|',end='')
        if i < nr:
            print('{:>15}  {:<13}'.format(defs_statement[i][1], defs_statement[i][0]),sep='',end='')
        else:
            print('{:^30}'.format(''),sep='',end='')
        print()

    return True

def main():
    global TOOLS_ROOT
    executable = __file__
    if os.path.islink(executable):
        executable = os.path.realpath(executable)
    TOOLS_ROOT = os.path.realpath(os.path.normpath(os.path.join(os.path.dirname(executable),'..')))

    parser = argparse.ArgumentParser(description=
'''
Tools for ICPC style problem sets.
Run this from one of:
    - the repository root, and supply `contest`
    - a contest directory
    - a problem directory
''', formatter_class = argparse.RawTextHelpFormatter)
    parser.add_argument('-v','--verbose', action='count',
            help='Verbose output; once for what\'s going on, twice for all intermediate output.')
    parser.add_argument('-c', '--contest', help='The contest to use, when running from repository root.')

    subparsers = parser.add_subparsers(title='actions', dest='action')
    subparsers.required = True

    # New contest
    runparser = subparsers.add_parser('contest', aliases=['new-contest', 'create-contest', 'add-contest'],
            help='Add a new contest to the current directory.')
    runparser.add_argument('contestname', help='The name of the contest, [a-z0-9]+.')

    # New problem
    runparser = subparsers.add_parser('problem', aliases=['new-problem', 'create-problem', 'add-problem'],
            help='Add a new problem to the current directory.')
    runparser.add_argument('problemname', help='The name of the problem, [a-z0-9]+.')

    # Problem statements
    pdfparser = subparsers.add_parser('pdf', aliases=['build', 'statement'],
            help='Build the problem statement pdf.')
    pdfparser.add_argument('-a', '--all', action='store_true', help='Create problem statements for individual problems as well.')

    # Solution slides
    solparser = subparsers.add_parser('solutions', aliases=['sol', 'slides'],
            help='Build the solution slides pdf.')
    solparser.add_argument('-a', '--all', action='store_true', help='Create problem statements for individual problems as well.')

    # Validation
    subparsers.add_parser('validate', aliases=['grammar'], help='validate all grammar')
    subparsers.add_parser('input', aliases=['in'], help='validate input grammar')
    subparsers.add_parser('output', aliases=['out'], help='validate output grammar')
    subparsers.add_parser('constraints', aliases=['con', 'bounds'], help='prints all the constraints found in problemset and validators')

    # Stats
    subparsers.add_parser('stats', aliases=['stat', 'status'], help='show statistics for contest/problem')

    # Generate
    genparser = subparsers.add_parser('generate', aliases=['gen'], help='generate answers testcases')
    genparser.add_argument('-f', '--force', action='store_true', help='Overwrite answers that have changed.')
    genparser.add_argument('submission',  nargs='?',
                    help='The program to generate answers. Defaults to first found.')

    # Run
    runparser = subparsers.add_parser('run', help='run programs and check answers')
    runparser.add_argument('-l', '--lazy', action='store_true', help='stop on first TLE or RTE')
    runparser.add_argument('-t', '--table', action='store_true', help='Print a submissions x testcases table for analysis.')
    runparser.add_argument('submissions', nargs='*', help='optionally supply a single program to run')

    # Sort
    subparsers.add_parser('sort', help='sort the problems for a contest by name')

    # All
    subparsers.add_parser('all', help='validate input, validate output, and run programs')

    # Build DomJudge zip
    zipparser = subparsers.add_parser('zip', help='Create zip file that can be imported into omJudge')
    zipparser.add_argument('-c', '--contest', action='store_true', help='Also create a contest zip containing problem zips, problems statements, and solution slides.')
    zipparser.add_argument('-s', '--skip', action='store_true', help='Skip recreation of problem zips.')
    zipparser.add_argument('-f', '--force', action='store_true', help='Skip validation of input and output files.')
    zipparser.add_argument('--tex', action='store_true', help='Store all relevant files in the problem statement directory.')
    zipparser.add_argument('--kattis', action='store_true', help='Small modifications to the kattis problemarchive.com format.')



    # Process arguments
    global args
    args = parser.parse_args()
    global verbose
    verbose = args.verbose if args.verbose else 0
    action = args.action

    if action in ['contest', 'new-contest', 'create-contest', 'add-contest']:
        shutil.copytree(os.path.join(TOOLS_ROOT,'skel/contest'), args.contestname)
        exit()

    if action in ['problem', 'new-problem', 'create-problem', 'add-problem']:
        shutil.copytree(os.path.join(TOOLS_ROOT,'/skel/problem'), args.problemname)
        exit()


    # Get problems and cd to contest
    problems, level, contest = get_problems(args.contest)

    if action in ['generate', 'gen']:
        if level != 'problem':
            print('Generating output files only works for a single problem.')
            exit()

    if action == 'run' and args.submissions:
        if level != 'problem':
            print('Running a given submission only works from a problem directory.')
            exit()

    if action in ['stats', 'status', 'stat']:
        stats(problems)
        return
    if action == 'sort':
        print_sorted(problems, args)
        return

    problem_zips = []

    success = True
    for problem in problems:
        print(_c.bold,'PROBLEM', problem,_c.reset)

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
            generate_output(problem,settings)
        if action in ['validate', 'grammar', 'output', 'out', 'all']:
            success &= validate(problem, 'output', settings)
        if action in ['run', 'all']:
            success &= run_submissions(problem, settings)
        if action in ['constraints', 'bounds', 'con']:
            success &= check_constraints(problem, settings)
        if action in ['zip']:
            output = re.sub(r'[^a-z0-9]', '', os.path.basename(os.path.normpath(problem)).lower()) + '.zip'
            print('OUTPUT: ', output)
            problem_zips.append(output)
            if not args.skip:
                success &= build_problem_pdf(problem, True)
                if not args.force:
                    success &= validate(problem, 'input', settings)
                    success &= validate(problem, 'output', settings)

                # Write to problemname.zip, where we strip all non-alphanumeric from the
                # problem directory name.
                success &= build_problem_zip(problem, output, settings)
        print()
        print()

    # build pdf for the entire contest
    if action in ['pdf', 'build', 'statement'] and level == 'contest':
        # Run 3 times, to fix the TOC.
        success &= build_contest_pdf(contest, problems)
        success &= build_contest_pdf(contest, problems)
        success &= build_contest_pdf(contest, problems)

    if action in ['sol', 'solutions', 'slides'] and level == 'contest':
        success &= build_contest_pdf(contest, problems, solutions=True)

    if action in ['zip'] and args.contest:
        success &= build_contest_pdf(contest, problems)
        success &= build_contest_pdf(contest, problems)
        success &= build_contest_pdf(contest, problems)
        success &= build_contest_pdf(contest, problems, web=True)
        success &= build_contest_pdf(contest, problems, solutions=True)

        build_contest_zip(problem_zips, contest+'.zip', args)


    if not success:
        exit()

if __name__ == '__main__':
    main()
shutil.rmtree(tmpdir)

