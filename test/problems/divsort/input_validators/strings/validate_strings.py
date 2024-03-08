#!/usr/bin/env python3

import re
import sys

line = sys.stdin.readline()
if not len(line.split()) == 4:
    print("Expected 4 tokens, got {len(line.split())}", file=sys.stderr)
    sys.exit(43)
_, _, c, d = line.split()
if not re.match(r"[a-zA-Z]+", c) or not re.match(r"[a-zA-Z]+", d):
    print("a-zA-Z expected", file=sys.stdout)
    sys.exit(43)
if '--sorted' in sys.argv[1:]:
    if list(c) != sorted(c) and sorted(d) == sorted(d):
        print(f"expected sorted input, got {c} and {d}", file=sys.stdout)
        sys.exit(43)
sys.exit(42)
