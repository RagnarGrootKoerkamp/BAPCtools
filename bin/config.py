# Global variables that are constant after the programs arguments have been
# parsed.

from pathlib import Path
import re

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

#VALIDATOR_FLAGS = ['

MAX_PRIORITY = max(PRIORITY.values())
MAX_PRIORITY_VERDICT = [v for v in PRIORITY if PRIORITY[v] == MAX_PRIORITY]

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD = 4

FILE_NAME_REGEX = '[a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]'
COMPILED_FILE_NAME_REGEX = re.compile(FILE_NAME_REGEX)

KNOWN_DATA_EXTENSIONS = [
    '.in', '.ans', '.interaction', '.hint', '.desc', '.png', '.jpg', '.svg'
]


# The root directory of the BAPCtools repository.
tools_root = Path(__file__).resolve().parent.parent

# Below here is some global state that will be filled in main().

args = None

# The number of warnings and errors encountered.
# The program will return non-zero when the number of errors is nonzero.
n_error = 0
n_warn = 0

# Return the command line timeout or the default of 30 seconds.
def timeout():
    if hasattr(args, 'timeout'): return args.timeout
    return 30


RUNNING_TEST = False
