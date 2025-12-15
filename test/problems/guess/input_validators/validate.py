#!/usr/bin/env python3
import re
import sys

integer = "(0|-?[1-9]\d*)"
pat = "(fixed|random|adaptive) " + integer + "\n"

line = sys.stdin.readline()
assert re.match(pat, line)

line = sys.stdin.readline()
assert len(line) == 0

# Nothing to report
sys.exit(42)
