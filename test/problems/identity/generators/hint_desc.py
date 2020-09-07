#!/usr/bin/env python3
import sys
from pathlib import Path

name, n = sys.argv[1:]
Path(name).with_suffix('.in').write_text(n + '\n')
Path(name).with_suffix('.ans').write_text(n + '\n')
Path(name).with_suffix('.hint').write_text('hint: '+ n + '\n')
Path(name).with_suffix('.desc').write_text('description: '+ n + '\n')
