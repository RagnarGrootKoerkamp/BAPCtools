#!/usr/bin/env python3
import sys
from pathlib import Path

n = sys.argv[1]
Path('testcase.in').write_text(n + '\n')
Path('testcase.ans').write_text(n + '\n')
Path('testcase.hint').write_text('hint: ' + n + '\n')
Path('testcase.desc').write_text('description: ' + n + '\n')
