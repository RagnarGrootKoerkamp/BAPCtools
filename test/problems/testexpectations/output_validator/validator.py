#!/usr/bin/env python3
import pathlib
import sys


def wrong_answer(message: str):
    judgemessage = pathlib.Path(sys.argv[3]) / "judgemessage.txt"
    judgemessage.write_text(message)
    sys.exit(43)  # WA


test_in = int(pathlib.Path(sys.argv[1]).read_text())
team_ans = sys.stdin.read().strip()

try:
    team_ans = int(team_ans)
except ValueError:
    pass

if test_in != team_ans:
    wrong_answer(f"expected '{test_in}', got '{team_ans}'")

sys.exit(42)  # AC
