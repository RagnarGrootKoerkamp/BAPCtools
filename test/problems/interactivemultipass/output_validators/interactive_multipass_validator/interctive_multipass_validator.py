#!/usr/bin/env python3
import sys
import pathlib

test_in = int(pathlib.Path(sys.argv[1]).read_text())
print(test_in)  # Simulate behaviour of normal multipass problem
team_ans = int(input())
if test_in < 0:
    # first pass
    if team_ans < 0:
        sys.exit(43)  # WA
    nextpass = pathlib.Path(sys.argv[3]) / 'nextpass.in'
    nextpass.write_text(str(team_ans))
    sys.exit(42)  # AC + nextpass.in => next run
else:
    # second pass
    if test_in == team_ans:
        sys.exit(42)  # AC
    else:
        sys.exit(43)  # WA
