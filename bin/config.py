# Global variables that are constant after the programs arguments have been
# parsed.

from pathlib import Path
import tempfile

# return values
RTV_AC = 42
RTV_WA = 43

BUILD_EXTENSIONS = ['.c', '.cc', '.cpp', '.java', '.py', '.py2', '.py3', '.ctd']
PROBLEM_OUTCOMES = ['ACCEPTED', 'WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED', 'RUN_TIME_ERROR']

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD = 4

tmpdir = Path(tempfile.mkdtemp(prefix='bapctools_'))

tools_root = Path(__file__).resolve().parent.parent

# this is lifted for convenience
args = None
verbose = False
