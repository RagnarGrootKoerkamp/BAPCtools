#!/usr/bin/env python3
import sys
from pathlib import Path

n = sys.argv[1]
Path('testcase.in').write_text(n + '\n')
Path('testcase.ans').write_text(n + '\n')
