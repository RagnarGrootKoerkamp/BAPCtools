# Global variables that are constant after the programs arguments have been
# parsed.

from pathlib import Path
import tempfile

# return values
RTV_AC = 42
RTV_WA = 43

BUILD_EXTENSIONS = ['.c', '.cc', '.cpp', '.java', '.py', '.py2', '.py3', '.ctd']
PROBLEM_OUTCOMES = ['ACCEPTED', 'WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR']
# Judging stops as soon as a max priority verdict is found.
PRIORITY = {
    'ACCEPTED': 0,
    'WRONG_ANSWER': 99,
    'TIME_LIMIT_EXCEEDED': 99,
    'RUN_TIME_ERROR': 99,
}

MAX_PRIORITY = max(PRIORITY.values())
MAX_PRIORITY_VERDICT = [v for v in PRIORITY if PRIORITY[v] == MAX_PRIORITY]

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD = 4

tools_root = Path(__file__).resolve().parent.parent

tmpdir = None

# This is lifted for convenience.
args = None
verbose = False

# The number of warnings and errors encountered.
# The program will return non-zero when the number of errors is nonzero.
n_error = 0
n_warn = 0
