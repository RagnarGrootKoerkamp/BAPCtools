#! /usr/bin/env python3

import re
import sys

line = sys.stdin.readline()
if not re.match("([1-9][0-9]*)\n", line):
    print("Positive integer expected", file=sys.stderr)
    sys.exit(43)
n = int(line)
for _ in range(n):
    line = sys.stdin.readline()
    try:
        x = float(line)
    except ValueError:
        print("Float expected, got {x}", file=sys.stderr)
        sys.exit(43)
sys.exit(42)
