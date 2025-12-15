#!/usr/bin/env python3
import pathlib
import sys


def wrong_answer(message: str):
    judgemessage = pathlib.Path(sys.argv[3]) / "judgemessage.txt"
    judgemessage.write_text(message)
    sys.exit(43)  # WA


test_in = int(pathlib.Path(sys.argv[1]).read_text())
print(test_in)  # Simulate behaviour of normal multipass problem
try:
    team_ans_string = input()
    try:
        team_ans = int(team_ans_string)
    except ValueError:
        wrong_answer(f"team output '{team_ans_string}' is not an integer")
except EOFError:
    wrong_answer("no input from team")

if test_in < 0:
    # first pass
    if team_ans < 0:
        wrong_answer(f"1st pass: team output ({team_ans}) is negative")
    nextpass = pathlib.Path(sys.argv[3]) / "nextpass.in"
    nextpass.write_text(str(team_ans))
    sys.exit(42)  # AC + nextpass.in => next run
else:
    # second pass
    if test_in != team_ans:
        wrong_answer(f"2nd pass: team output ({team_ans}) is not equal to test input ({test_in})")

try:
    more_input = input()
    wrong_answer(f'extra input from team, starting with "{more_input}"')
except EOFError:
    sys.exit(42)  # AC
