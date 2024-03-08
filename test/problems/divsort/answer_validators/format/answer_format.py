#!/usr/bin/env python3

import sys
import re

line = sys.stdin.readline()
if not re.match(r"\d+(\.\d+)? [a-zA-Z]+\n", line):
    print("Invalid format", file=sys.stderr)
    sys.exit(43)
tokens = line.split()

if not re.match("[a-z]+", tokens[1]):
    print("Lowercase .ans files expected", file=sys.stderr)
    sys.exit(43)

sys.exit(42)
