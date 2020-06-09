import sys
from pathlib import Path

name = sys.argv[1]
Path(name).with_suffix('.in').write_text('input\n')
Path(name).with_suffix('.ans').write_text('1\n')
