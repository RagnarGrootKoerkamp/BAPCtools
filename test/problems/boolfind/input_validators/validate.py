#!/usr/bin/env python3

import sys
import re


try:
    line = sys.stdin.readline()
    if not re.match(r"[1-9][0-9]*\n", line):
        sys.exit(43)
    runs = int(line)
    for _ in range(runs):
        line = sys.stdin.readline()
        if not re.match(r"[1-9][0-9]*\n", line):
            sys.exit(43)
        n = int(line)
        for _ in range(n):
            line = sys.stdin.readline()
            if not re.match(r"(0|1)\n", line):
                sys.exit(43)
except UnicodeDecodeError:
    sys.exit(43)

if not sys.stdin.readline() == "":
    sys.exit(43)

sys.exit(42)

