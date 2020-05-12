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
    'WRONG_ANSWER': 99,
    'TIME_LIMIT_EXCEEDED': 99,
    'RUN_TIME_ERROR': 99,
}

VALIDATION_MODES = ['default', 'custom', 'custom interactive']

MAX_PRIORITY = max(PRIORITY.values())
MAX_PRIORITY_VERDICT = [v for v in PRIORITY if PRIORITY[v] == MAX_PRIORITY]

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD = 4

tools_root = Path(__file__).resolve().parent.parent

tmpdir = None

# This is lifted for convenience.
args = None
# TODO: Just use config.args.verbose instead.
verbose = False

# TODO: Ideally we parse arguments at the beginning so that `default` isn't needed here.
def arg(name, default = None): return getattr(args, name, default) or default

# Return the command line timeout or the default of 30 seconds.
def timeout(): return arg('timeout', 30)


# The number of warnings and errors encountered.
# The program will return non-zero when the number of errors is nonzero.
n_error = 0
n_warn = 0

FILE_NAME_REGEX = '[a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]'
COMPILED_FILE_NAME_REGEX = re.compile(FILE_NAME_REGEX)

KNOWN_DATA_EXTENSIONS = [
    '.in', '.ans', '.interaction', '.hint', '.desc', '.png', '.jpg', '.jpeg', '.svg'
]
