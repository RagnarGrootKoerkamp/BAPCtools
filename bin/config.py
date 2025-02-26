# Global variables that are constant after the programs arguments have been parsed.

import argparse
import os
import re
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Final, Literal, Optional

# return values
RTV_AC: Final[int] = 42
RTV_WA: Final[int] = 43

SUBMISSION_DIRS: Final[Sequence[str]] = [
    "accepted",
    "wrong_answer",
    "time_limit_exceeded",
    "run_time_error",
]

# This ordering is shown in bt new_problem with questionary installed (intentionally non-alphabetical).
KNOWN_LICENSES: Final[Sequence[str]] = [
    "cc by-sa",
    "cc by",
    "cc0",
    "public domain",
    "educational",
    "permission",
    "unknown",
]

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD: Final[int] = 4

FILE_NAME_REGEX: Final[str] = "[a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]"
COMPILED_FILE_NAME_REGEX: Final[re.Pattern[str]] = re.compile(FILE_NAME_REGEX)

CONSTANT_NAME_REGEX = "[a-zA-Z_][a-zA-Z0-9_]*"
COMPILED_CONSTANT_NAME_REGEX: Final[re.Pattern[str]] = re.compile(CONSTANT_NAME_REGEX)
CONSTANT_SUBSTITUTE_REGEX: Final[re.Pattern[str]] = re.compile(
    f"\\{{\\{{({CONSTANT_NAME_REGEX})\\}}\\}}"
)

BAPCTOOLS_SUBSTITUTE_REGEX: Final[re.Pattern[str]] = re.compile(
    f"\\{{%({CONSTANT_NAME_REGEX})%\\}}"
)


KNOWN_TESTCASE_EXTENSIONS: Final[Sequence[str]] = [
    ".in",
    ".ans",
    ".out",
]

KNOWN_VISUALIZER_EXTENSIONS: Final[Sequence[str]] = [
    ".png",
    ".jpg",
    ".svg",
    ".pdf",
]

KNOWN_TEXT_DATA_EXTENSIONS: Final[Sequence[str]] = [
    *KNOWN_TESTCASE_EXTENSIONS,
    ".interaction",
    ".hint",
    ".desc",
    ".in.statement",
    ".ans.statement",
    #'.args',
]

KNOWN_DATA_EXTENSIONS: Final[Sequence[str]] = [
    *KNOWN_TEXT_DATA_EXTENSIONS,
    *KNOWN_VISUALIZER_EXTENSIONS,
]

INVALID_CASE_DIRECTORIES: Final[Sequence[str]] = [
    "invalid_input",
    "invalid_answer",
    "invalid_output",
    "bad",
]


SEED_DEPENDENCY_RETRIES: Final[int] = 10

# The root directory of the BAPCtools repository.
TOOLS_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# The directory from which BAPCtools is invoked.
current_working_directory: Final[Path] = Path.cwd().resolve()

# Add third_party/ to the $PATH for checktestdata.
os.environ["PATH"] += os.pathsep + str(TOOLS_ROOT / "third_party")

# Below here is some global state that will be filled in main().

args = argparse.Namespace()

DEFAULT_ARGS: Final[Mapping] = {
    "jobs": (os.cpu_count() or 1) // 2,
    "time": 600,  # Used for `bt fuzz`
    "verbose": 0,
    "languages": None,
}


# The list of arguments below is generated using the following command:
"""
for cmd in $(bapctools --help | grep '^  {' | sed 's/  {//;s/}//;s/,/ /g') ; do bapctools $cmd --help ; done |& \
grep '^  [^ ]' | sed 's/^  //' | cut -d ' ' -f 1 | sed -E 's/,//;s/^-?-?//;s/-/_/g' | sort -u | \
grep -Ev '^(h|jobs|time|verbose)$' | sed "s/^/'/;s/$/',/" | tr '\n' ' ' | sed 's/^/ARGS_LIST: Final[Sequence[str]] = [/;s/, $/]\n/'
"""
# fmt: off
ARGS_LIST: Final[Sequence[str]] = ['1', 'add', 'all', 'answer', 'api', 'author', 'check_deterministic', 'clean', 'colors', 'contest', 'contest_id', 'contestname', 'cp', 'default_solution', 'depth', 'directory', 'error', 'force', 'force_build', 'generic', 'input', 'interaction', 'interactive', 'invalid', 'kattis', 'language', 'memory', 'more', 'move_to', 'no_bar', 'no_generate', 'no_solution', 'no_solutions', 'no_testcase_sanity_checks', 'no_time_limit', 'no_validators', 'no_visualizer', 'open', 'order', 'order_from_ccs', 'overview', 'password', 'post_freeze', 'problem', 'problemname', 'remove', 'reorder', 'samples', 'sanitizer', 'skel', 'skip', 'sort', 'submissions', 'table', 'testcases', 'time_limit', 'timeout', 'token', 'tree', 'type', 'username', 'valid_output', 'watch', 'web', 'write']
# fmt: on


def set_default_args() -> None:
    # Set default argument values.
    for arg in ARGS_LIST:
        if not hasattr(args, arg):
            setattr(args, arg, None)
    for arg, value in DEFAULT_ARGS.items():
        if not hasattr(args, arg):
            setattr(args, arg, value)


level: Optional[Literal["problem", "problemset"]] = None

# The number of warnings and errors encountered.
# The program will return non-zero when the number of errors is nonzero.
n_error: int = 0
n_warn: int = 0


# Set to true when running as a test.
RUNNING_TEST: bool = False
TEST_TLE_SUBMISSIONS: bool = False


# Randomly generated uuid4 for BAPCtools
BAPC_UUID: Final[str] = "8ee7605a-d1ce-47b3-be37-15de5acd757e"
BAPC_UUID_PREFIX: Final[int] = 8
