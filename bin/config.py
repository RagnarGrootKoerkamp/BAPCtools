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
    'time': 600,
    'verbose': 0,
}


def set_default_args():
    # Set default argument values
    for arg in [
        '1',
        'add_manual',
        'all',
        'check_deterministic',
        'clean',
        'clean_generated',
        'cleanup_generated',
        'cp',
        'cpp_flags',
        'contest',
        'contest_id',
        'default_solution',
        'error',
        'force',
        'force_build',
        'ignore_validators',
        'input',
        'interaction',
        'interactive',
        'kattis',
        'memory',
        'move_manual',
        'move_to',
        'no_bar',
        'no_generate',
        'no_solutions',
        'no_timelimit',
        'order',
        'order_from_ccs',
        'output',
        'problem',
        'remove',
        'samples',
        'scoreboard_repo',
        'skel',
        'skip',
        'submissions',
        'table',
        'testcases',
        'timelimit',
        'timeout',
        'watch',
        'web',
    ]:
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
