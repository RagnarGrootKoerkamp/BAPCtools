#!/usr/bin/env python3
import sys

input_file = open(sys.argv[1]).read().strip()
answer_file = open(sys.argv[2]).read().strip()
# input yields the team output
args = sys.argv[4:]
with open(f"{sys.argv[3]}/judgeimage.svg", "w") as f:
    # this is unsafe since args could contain svg tags
    print(f"<svg><text>args: {args}</text></svg>", file=f)
