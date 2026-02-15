#!/usr/bin/env python3
import re
import sys

integer = "(0|-?[1-9]\d*)"

MAX = 10**15

cases = 0

while True:
    line = sys.stdin.readline()
    if len(line) == 0:
        break
    assert re.match(integer + " " + integer + "\n", line), f"'{line}' is not a pair of integers"
    (n, m) = map(int, line.split())
    assert 0 <= n <= MAX, f"{n} not in [0, {MAX}]"
    assert 0 <= m <= MAX, f"{n} not in [0, {MAX}]"
    cases += 1

assert 1 <= cases <= 40, f"invalid number of cases {cases} not in [1,40]"

# Nothing to report
sys.exit(42)
