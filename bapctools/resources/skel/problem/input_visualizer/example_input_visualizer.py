#!/usr/bin/env python3
import sys

input_file = open(sys.argv[1]).read().strip()
answer_file = open(sys.argv[2]).read().strip()
args = sys.argv[3:]
with open("testcase.svg", "w") as f:
    # this is unsafe since args could contain svg tags
    print(f"<svg><text>args: {args}</text></svg>", file=f)
