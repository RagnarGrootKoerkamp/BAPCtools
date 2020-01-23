# read problem settings from config files

import shutil
import config
import yaml
import subprocess
import sys
import os
from pathlib import Path


def is_windows():
    return sys.platform in ['win32', 'cygwin']


if not is_windows():
    import resource


# color printing
class Colorcodes(object):
    def __init__(self):
        if not is_windows():
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
        else:
            self.bold = ''
            self.reset = ''
            self.blue = ''
            self.green = ''
            self.orange = ''
            self.red = ''
            self.white = ''

            self.boldblue = ''
            self.boldgreen = ''
            self.boldorange = ''
            self.boldred = ''


_c = Colorcodes()


def log(msg):
    print(_c.green + 'LOG: ' + msg + _c.reset)


def warn(msg):
    print(_c.orange + 'WARNING: ' + msg + _c.reset)
    config.n_warn += 1


def error(msg):
    print(_c.red + 'ERROR: ' + msg + _c.reset)
    config.n_error += 1


def fatal(msg):
    print(_c.red + 'FATAL: ' + msg + _c.reset)
    exit(1)


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
        self.carriage_return = '\r' if is_windows() else '\033[K'

    def total_width(self):
        return shutil.get_terminal_size().columns

    def bar_width(self):
        if self.item_width is None: return None
        return self.total_width() - len(self.prefix) - 2 - self.item_width - 1

    def update(self, count, max_len):
        self.count += count
        self.item_width = max(self.item_width, max_len) if self.item_width else max_len

    def clearline(self):
        if hasattr(config.args, 'no_bar') and config.args.no_bar: return
        print(self.carriage_return, end='', flush=True)

    def action(prefix, item, width=None, total_width=None):
        if width is not None and total_width is not None and len(prefix) + 2 + width > total_width:
            width = total_width - len(prefix) - 2
        if width is not None and len(item) > width: item = item[:width]
        if width is None: width = 0
        s = f'{_c.blue}{prefix}{_c.reset}: {item:<{width}}'
        return s

    def get_prefix(self):
        return ProgressBar.action(self.prefix, self.item, self.item_width, self.total_width())

    def get_bar(self):
        bar_width = self.bar_width()
        if self.count is None or bar_width < 4: return ''
        fill = (self.i - 1) * (bar_width - 2) // self.count
        return '[' + '#' * fill + '-' * (bar_width - 2 - fill) + ']'

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
        self.clearline()
        self.logged = True
        print(self.get_prefix(), message, flush=True)

    def warn(self, message=''):
        config.n_warn += 1
        self.log(_c.orange + message + _c.reset)

    def error(self, message=''):
        config.n_error += 1
        self.log(_c.red + message + _c.reset)

    # Return True when something was printed
    def done(self, success=True, message=''):
        self.clearline()
        if self.logged: return False
        if not success: config.n_error += 1
        if config.verbose or not success:
            self.log(message)
            return True
        return False


def read_yaml(path):
    settings = {}
    if path.is_file():
        with path.open() as yamlfile:
            config = yaml.safe_load(yamlfile)
            if config is None: return None
            if isinstance(config, list): return config
            for key, value in config.items():
                settings[key] = '' if value is None else value
    return settings


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
            warn(f'Ignoring the --samples flag because testcases are explicitly listed.')
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
        infiles = list(glob(problem, 'data/sample/**/*.in'))
        if not samplesonly:
            infiles += list(glob(problem, 'data/secret/**/*.in'))

    testcases = []
    for f in infiles:
        if needans and not f.with_suffix('.ans').is_file():
            warn(f'Found input file {str(f)} without a .ans file.')
            continue
        testcases.append(f.with_suffix('.in'))
    testcases.sort()

    if len(testcases) == 0:
        warn(f'Didn\'t find any testcases for {str(problem)}')
    return testcases


def strip_newline(s):
    if s.endswith('\n'):
        return s[:-1]
    else:
        return s


def substitute(data, variables):
    for key in variables:
        r = ''
        if variables[key] != None: r = variables[key]
        data = data.replace('{%' + key + '%}', str(r))
    return data


def copy_and_substitute(inpath, outpath, variables):
    try:
        data = inpath.read_text()
    except UnicodeDecodeError:
        # skip this file
        warn(f'File "{inpath}" has no unicode encoding.')
        return
    data = substitute(data, variables)
    if outpath.is_symlink():
        outpath.unlink()
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
    if len(output) > 200:
        output = output[:200]
        output += ' ...\n'
        cropped = True

    if cropped:
        output += _c.orange + 'Use -e to show more or -E to hide it.' + _c.reset
    return output

# Return memory limit in bytes.
def get_memory_limit(kwargs=None):
    memory_limit = 1000000000  # 1GB
    if hasattr(config.args, 'memory'):
        if config.args.memory and config.args.memory != 'unlimited':
            memory_limit = int(config.args.memory)
        else:
            memory_limit = None
    if kwargs and 'memory' in kwargs:
        memory_limit = kwargs['memory']
        kwargs.pop('memory')
    return memory_limit


# Return the time limits: a pair (problem time limit, hard wall timeout)
# problem time limit: default from problem config; overridden by --timelimit
# hard wall timeout: default 1.5*timelimit+1, overridden by --timeout
#   wall timeout will be at least time_limit+1 
#
# Note: This is only suitable for running submissions.
# Other programs should have a larger default timeout.
def get_time_limits(settings):
    time_limit = settings.timelimit
    if hasattr(config.args, 'timelimit'): time_limit = config.args.timelimit
    if time_limit is None: time_limit = 1

    timeout = 1.5*time_limit+1
    if hasattr(config.args, 'timeout') and config.args.timeout:
        timeout = max(config.args.timeout, time_limit+1)
    return time_limit, int(timeout)

# Return the command line timeout or the default of 30
def get_timeout():
    if hasattr(config.args, 'timeout') and config.args.timeout:
        return config.args.timeout
    return 30

# Run `command`, returning stderr if the return code is unexpected.
def exec_command(command, expect=0, crop=True, **kwargs):
    # By default: discard stdout, return stderr
    if 'stdout' not in kwargs: kwargs['stdout'] = subprocess.PIPE
    if 'stderr' not in kwargs: kwargs['stderr'] = subprocess.PIPE

    # Convert any Pathlib objects to string.
    command = [str(x) for x in command]

    if config.verbose >= 2:
        print(command, kwargs)

    timeout = 30
    if 'timeout' in kwargs:
        if kwargs['timeout']:
            timeout = kwargs['timeout']
        kwargs.pop('timeout')

    memory_limit = get_memory_limit(kwargs)

    # Disable memory limits for Java.
    if command[0] == 'java' or command[0] == 'javac':
        memory_limit = None

    # Note: Resource limits do not work on windows.
    def setlimits():
        resource.setrlimit(resource.RLIMIT_CPU, (timeout+1, timeout+1))
        # Increase the max stack size from default to the max available.
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_STACK,
                               (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
        if memory_limit:
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

    if not is_windows():
        process = subprocess.Popen(command, preexec_fn=setlimits, **kwargs)
    else:
        process = subprocess.Popen(command, **kwargs)
    try:
        (stdout, stderr) = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        (stdout, stderr) = process.communicate()
    except KeyboardInterrupt:
        fatal('Running interrupted.')

    def maybe_crop(s):
        return crop_output(s) if crop else s

    return (True if process.returncode == expect else process.returncode,
            maybe_crop(stderr.decode('utf-8')) if stderr is not None else None,
            maybe_crop(stdout.decode('utf-8')) if stdout is not None else None)
