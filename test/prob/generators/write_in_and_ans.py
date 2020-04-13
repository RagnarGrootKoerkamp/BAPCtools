import sys
from pathlib import Path

name = sys.argv[1]
Path(name).with_suffix('.in').write_text('input')
Path(name).with_suffix('.ans').write_text('answer')
