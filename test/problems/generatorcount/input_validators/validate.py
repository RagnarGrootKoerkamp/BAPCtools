#! /usr/bin/env python3

import re
import sys

line = sys.stdin.readline()
if not re.match(r"[a-z] (-?[1-9][0-9]*|0) (-?[1-9][0-9]*|0)\n", line):
    sys.exit(43)
_, x, y = line.split()
if int(x) == int(y):
    sys.exit(43)
sys.exit(42)
