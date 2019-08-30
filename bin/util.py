# read problem settings from config files

import shutil
import config
import yaml
import subprocess
import resource
import os
from pathlib import Path


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





# A class that draws a progressbar.
# Construct with a constant prefix, the max length of the items to process, and
# the number of items to process.
# When count is None, the bar itself isn't shown.
# Start each loop with bar.start(current_item), end it with bar.done(message).
# Optionally, multiple errors can be logged using bar.log(error). If so, the
# final message on bar.done() will be ignored.
class ProgressBar:
    def __init__(self, prefix, max_len=None, count=None):
        self.prefix = prefix  # The prefix to always print
        self.item_width = max_len  # The max length of the items we're processing
        self.count = count  # The number of items we're processing
        self.i = 0
        self.total_width = shutil.get_terminal_size().columns  # The terminal width
        if self.item_width is not None:
            self.bar_width = self.total_width - len(self.prefix) - 2 - self.item_width - 1

    def update(self, count, max_len):
        self.count += count
        self.item_width = max(self.item_width, max_len) if self.item_width else max_len
        if self.item_width is not None:
            self.bar_width = self.total_width - len(self.prefix) - 2 - self.item_width - 1

    def clearline():
        if hasattr(config.args, 'no_bar') and config.args.no_bar: return
        print('\033[K', end='', flush=True)

    def action(prefix, item, width=None, total_width=None):
        if width is not None and total_width is not None and len(prefix) + 2 + width > total_width:
            width = total_width - len(prefix) - 2
        if width is not None and len(item) > width: item = item[:width]
        if width is None: width = 0
        s = f'{_c.blue}{prefix}{_c.reset}: {item:<{width}}'
        return s

    def get_prefix(self):
        return ProgressBar.action(self.prefix, self.item, self.item_width,
                self.total_width)

    def get_bar(self):
        if self.count is None or self.bar_width < 4: return ''
        fill = (self.i - 1) * (self.bar_width - 2) // self.count
        return '[' + '#' * fill + '-' * (self.bar_width - 2 - fill) + ']'

    def start(self, item=''):
        self.i += 1
        assert self.count is None or self.i <= self.count

        self.item = item
        self.logged = False

        if hasattr(config.args, 'no_bar') and config.args.no_bar: return

        prefix = self.get_prefix()
        bar = self.get_bar()

        if bar is None or bar == '':
            print(self.get_prefix(), end='\r', flush=True)
        else:
            print(self.get_prefix(), self.get_bar(), end='\r', flush=True)

    # Done can be called multiple times to make multiple persistent lines.
    # Make sure that the message does not end in a newline.
    def log(self, message=''):
        ProgressBar.clearline()
        self.logged = True
        print(self.get_prefix(), message, flush=True)

    # Return True when something was printed
    def done(self, success=True, message=''):
        ProgressBar.clearline()
        if self.logged: return False
        if not success: config.n_error += 1
        if config.verbose or not success:
            self.log(message)
            return True
        return False


def read_configs(problem):
    # some defaults
    settings = {
        'probid': 'A',
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
    yamlpath = problem / 'problem.yaml'
    if yamlpath.is_file():
        with yamlpath.open() as yamlfile:
            try:
                config = yaml.safe_load(yamlfile)
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
    domjudge_path = problem / 'domjudge-problem.ini'
    if domjudge_path.is_file():
        with domjudge_path.open() as f:
            for line in f.readlines():
                key, var = line.strip().split('=')
                var = var[1:-1]
                settings[key] = float(var) if key == 'timelimit' else var

    return settings


# TODO: Make this return [(problem, config)] only.
# sort problems by the id in domjudge-problem.ini, and secondary by name
# return [(problem, id, config)]
def sort_problems(problems):
    configs = [(problem, read_configs(problem)) for problem in problems]
    problems = [(pair[0], pair[1]['probid'], pair[1]) for pair in configs if 'probid' in pair[1]]
    problems.sort(key=lambda x: (x[1], x[0]))
    return problems


def is_hidden(path):
    for d in path.parts:
        if d[0] == '.':
            return True
    return False


# glob, but without hidden files
def glob(path, expression):
    return sorted([p for p in path.glob(expression) if not is_hidden(p)])


# testcases; returns list of basenames
def get_testcases(problem, needans=True, only_sample=False):
    # Require both in and ans files
    samplesonly = only_sample or hasattr(config.args, 'samples') and config.args.samples
    infiles = None
    if hasattr(config.args, 'testcases') and config.args.testcases:
      if samplesonly:
        config.n_warn += 1
        print(f'{_c.red}Ignoring the --samples flag because testcases are explicitly listed.{_c.reset}')
      # Deduplicate testcases with both .in and .ans.
      infiles = []
      for t in config.args.testcases:
          if Path(problem / t).is_dir():
            infiles += glob(Path(problem / t), '**/*.in')
          else:
            infiles.append(Path(problem / t))

      infiles = [t.with_suffix('.in') for t in infiles]
      infiles = list(set(infiles))
    else:
        infiles = list(glob(problem, 'data/sample/*.in'))
        if not samplesonly:
            infiles += list(glob(problem, 'data/secret/*.in'))

    testcases = []
    for f in infiles:
        if needans and not f.with_suffix('.ans').is_file():
            config.n_warn += 1
            print(f'{_c.red}Found input file {str(f)} without a .ans file.{_c.reset}')
            continue
        testcases.append(f.with_suffix('.in'))
    testcases.sort()

    if len(testcases) == 0:
        config.n_warn += 1
    return testcases


def strip_newline(s):
    if s.endswith('\n'):
        return s[:-1]
    else:
        return s


def substitute(data, variables):
    for key in variables:
        if variables[key] == None: continue
        data = data.replace('{%' + key + '%}', str(variables[key]))
    return data


def copy_and_substitute(inpath, outpath, variables):
    data = inpath.read_text()
    data = substitute(data, variables)
    outpath.write_text(data)


def substitute_file_variables(path, variables):
    copy_and_substitute(path, path, variables)


def substitute_dir_variables(dirname, variables):
    for path in dirname.rglob('*'):
        if path.is_file():
            substitute_file_variables(path, variables)


def crop_output(output):
    if config.args.noerror: return None
    if config.args.error: return output

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
            numlines -
            8) + ' lines skipped; use -e to show them or -E to hide all output.' + _c.reset
    return output


# Run `command`, returning stderr if the return code is unexpected.
def exec_command(command, expect=0, crop=True, **kwargs):
    # By default: discard stdout, return stderr
    if 'stdout' not in kwargs: kwargs['stdout'] = subprocess.PIPE
    if 'stderr' not in kwargs: kwargs['stderr'] = subprocess.PIPE

    if config.verbose >= 2:
        print(command, kwargs)

    timeout = None
    hard_timeout = 60 # Kill a program after 60s cpu time
    if 'timeout' in kwargs:
        timeout = kwargs['timeout']
        kwargs.pop('timeout')
        if timeout is not None:
            hard_timeout = timeout + 1

    memory_limit = 1000000000 # 1GB
    if hasattr(config.args, 'memory') and config.args.memory:
        memory_limit = int(config.args.memory)
    if 'memory' in kwargs:
        memory_limit = kwargs['memory']
        kwargs.pop('memory')
    # Disable memory limits for Java.
    if command[0] == 'java' or command[0] == 'javac':
        memory_limit = None

    def setlimits():
        resource.setrlimit(resource.RLIMIT_CPU, (hard_timeout, hard_timeout))
        if memory_limit:
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

    process = subprocess.Popen(command, preexec_fn=setlimits, **kwargs)
    try:
        (stdout, stderr) = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        (stdout, stderr) = process.communicate()
    except KeyboardInterrupt:
        print(f'{_c.red}Running interrupted.{_c.reset}')
        exit(1)

    def maybe_crop(s):
        return crop_output(s) if crop else s

    return (True if process.returncode == expect else process.returncode,
            maybe_crop(stderr.decode('utf-8')) if stderr is not None else None,
            maybe_crop(stdout.decode('utf-8')) if stdout is not None else None)
