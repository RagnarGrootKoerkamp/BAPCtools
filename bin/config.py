# Global variables that are constant after the programs arguments have been
# parsed.

from pathlib import Path
import re
import os
import argparse

# return values
RTV_AC = 42
RTV_WA = 43

VERDICTS = ['ACCEPTED', 'WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR']
# Judging stops as soon as a max priority verdict is found.
PRIORITY = {
    'INCONSISTENT_VALIDATORS': -1,
    'VALIDATOR_CRASH': -1,
    'ACCEPTED': 0,
    'WRONG_ANSWER': 90,
    'TIME_LIMIT_EXCEEDED': 99,
    'RUN_TIME_ERROR': 99,
}

VALIDATION_MODES = ['default', 'custom', 'custom interactive']

MAX_PRIORITY = max(PRIORITY.values())
MAX_PRIORITY_VERDICT = [v for v in PRIORITY if PRIORITY[v] == MAX_PRIORITY]

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD = 4

FILE_NAME_REGEX = '[a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]'
COMPILED_FILE_NAME_REGEX = re.compile(FILE_NAME_REGEX)

KNOWN_DATA_EXTENSIONS = [
    '.in',
    '.ans',
    '.interaction',
    '.hint',
    '.desc',
    '.png',
    '.jpg',
    '.svg',
    '.pdf',
    '.gif',
]

SEED_DEPENDENCY_RETRIES = 10

# The root directory of the BAPCtools repository.
tools_root = Path(__file__).resolve().parent.parent

# The directory from which BAPCtools is invoked.
current_working_directory = Path.cwd().resolve()

# Add third_party/ to the $PATH for checktestdata.
os.environ["PATH"] += os.pathsep + str(tools_root / 'third_party')

# Below here is some global state that will be filled in main().

args = argparse.Namespace()

default_args = {
    'jobs': os.cpu_count() // 2,
    'time': 600,  # Used for `bt fuzz`
    'verbose': 0,
}


# The list of arguments below is generated using the following command:
"""
for cmd in $(bapctools --help | grep '^  {' | sed 's/  {//;s/}//;s/,/ /g') ; do bapctools $cmd --help ; done |& \
grep '^  [^ ]' | sed 's/^  //' | cut -d ' ' -f 1 | sed -E 's/,//;s/^-?-?//;s/-/_/g' | sort -u | \
grep -Ev '^(h|jobs|time|verbose)$' | sed "s/^/'/;s/$/',/" | tr '\n' ' ' | sed 's/^/args_list = [/;s/, $/]\n/'
"""
# fmt: off
args_list = ['1', 'add_manual', 'all', 'api', 'author', 'check_deterministic', 'clean', 'clean_generated', 'cleanup_generated', 'colors', 'contest', 'contest_id', 'contestname', 'cp', 'cpp_flags', 'default_solution', 'directory', 'error', 'force', 'force_build', 'language', 'ignore_validators', 'input', 'interaction', 'interactive', 'kattis', 'memory', 'move_to', 'no_bar', 'no_generate', 'no_solutions', 'no_timelimit', 'order', 'order_from_ccs', 'output', 'password', 'post_freeze', 'problem', 'problemname', 'remove', 'samples', 'skel', 'skip', 'skip_solution', 'skip_testcase_sanity_checks', 'skip_visualizer', 'submissions', 'table', 'testcases', 'timelimit', 'timeout', 'token', 'username', 'validation', 'watch', 'web']
# fmt: on


def set_default_args():
    # Set default argument values.
    for arg in args_list:
        if not hasattr(args, arg):
            setattr(args, arg, None)
    for arg, value in default_args.items():
        if not hasattr(args, arg):
            setattr(args, arg, value)

level = None

# The number of warnings and errors encountered.
# The program will return non-zero when the number of errors is nonzero.
n_error = 0
n_warn = 0


# Set to true when running as a test.
RUNNING_TEST = False
TEST_TLE_SUBMISSIONS = False

# The default timeout used for generators, visualizer etc.
DEFAULT_TIMEOUT = 30
DEFAULT_INTERACTION_TIMEOUT = 60


def get_timeout():
    return args.timeout or DEFAULT_TIMEOUT
