# Global variables that are constant after the programs arguments have been
# parsed.

import argparse
import os
import re
from pathlib import Path
from typing import Literal, Optional

# return values
RTV_AC = 42
RTV_WA = 43

SUBMISSION_DIRS = [
    "accepted",
    "wrong_answer",
    "time_limit_exceeded",
    "run_time_error",
]

KNOWN_LICENSES = [
    "cc by-sa",
    "cc by",
    "cc0",
    "public domain",
    "educational",
    "permission",
    "unknown",
]

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD = 4

FILE_NAME_REGEX = "[a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]"
COMPILED_FILE_NAME_REGEX = re.compile(FILE_NAME_REGEX)

KNOWN_TESTCASE_EXTENSIONS = [
    ".in",
    ".ans",
    ".out",
]

KNOWN_VISUALIZER_EXTENSIONS = [
    ".png",
    ".jpg",
    ".svg",
    ".pdf",
]

KNOWN_TEXT_DATA_EXTENSIONS = KNOWN_TESTCASE_EXTENSIONS + [
    ".interaction",
    ".hint",
    ".desc",
    ".in.statement",
    ".ans.statement",
    #'.args',
]

KNOWN_DATA_EXTENSIONS = KNOWN_TEXT_DATA_EXTENSIONS + KNOWN_VISUALIZER_EXTENSIONS

INVALID_CASE_DIRECTORIES = [
    "invalid_inputs",
    "invalid_answers",
    "invalid_outputs",
    "bad",
]


SEED_DEPENDENCY_RETRIES = 10

# The root directory of the BAPCtools repository.
tools_root = Path(__file__).resolve().parent.parent

# The directory from which BAPCtools is invoked.
current_working_directory = Path.cwd().resolve()

# Add third_party/ to the $PATH for checktestdata.
os.environ["PATH"] += os.pathsep + str(tools_root / "third_party")

# Below here is some global state that will be filled in main().

args = argparse.Namespace()

default_args = {
    "jobs": (os.cpu_count() or 1) // 2,
    "time": 600,  # Used for `bt fuzz`
    "verbose": 0,
    "languages": None,
}


# The list of arguments below is generated using the following command:
"""
for cmd in $(bapctools --help | grep '^  {' | sed 's/  {//;s/}//;s/,/ /g') ; do bapctools $cmd --help ; done |& \
grep '^  [^ ]' | sed 's/^  //' | cut -d ' ' -f 1 | sed -E 's/,//;s/^-?-?//;s/-/_/g' | sort -u | \
grep -Ev '^(h|jobs|time|verbose)$' | sed "s/^/'/;s/$/',/" | tr '\n' ' ' | sed 's/^/args_list = [/;s/, $/]\n/'
"""
# fmt: off
args_list = ['1', 'add', 'all', 'answer', 'api', 'author', 'check_deterministic', 'clean', 'colors', 'contest', 'contest_id', 'contestname', 'cp', 'default_solution', 'depth', 'directory', 'error', 'force', 'force_build', 'input', 'interaction', 'interactive', 'invalid', 'kattis', 'language', 'memory', 'more', 'move_to', 'no_bar', 'no_generate', 'no_solution', 'no_solutions', 'no_testcase_sanity_checks', 'no_time_limit', 'no_validators', 'no_visualizer', 'open', 'order', 'order_from_ccs', 'overview', 'password', 'post_freeze', 'problem', 'problemname', 'remove', 'reorder', 'samples', 'sanitizer', 'skel', 'skip', 'sort', 'submissions', 'table', 'testcases', 'time_limit', 'timeout', 'token', 'tree', 'username', 'validation', 'watch', 'web', 'write']
# fmt: on


def set_default_args():
    # Set default argument values.
    for arg in args_list:
        if not hasattr(args, arg):
            setattr(args, arg, None)
    for arg, value in default_args.items():
        if not hasattr(args, arg):
            setattr(args, arg, value)


level: Optional[Literal["problem", "problemset"]] = None

# The number of warnings and errors encountered.
# The program will return non-zero when the number of errors is nonzero.
n_error = 0
n_warn = 0


# Set to true when running as a test.
RUNNING_TEST = False
TEST_TLE_SUBMISSIONS = False


# Randomly generated uuid4 for BAPCtools
BAPC_UUID = "8ee7605a-d1ce-47b3-be37-15de5acd757e"
BAPC_UUID_PREFIX = 8
