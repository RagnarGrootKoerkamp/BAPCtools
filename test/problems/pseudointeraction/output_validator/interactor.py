#!/usr/bin/env python3
import os
import pathlib
import random
import sys
import threading


def wrong_answer(message):
    judgemessage = pathlib.Path(sys.argv[3]) / "judgemessage.txt"
    judgemessage.write_text(message)
    sys.exit(43)  # WA


testcase = pathlib.Path(sys.argv[1]).read_text()
lines = testcase.splitlines()
n = int(lines[0])
numbers = list(map(int, lines[1:]))

assert len(numbers) <= n
random.seed(testcase)
while len(numbers) < n:
    numbers.append(random.randint(0, 10**9))


def print_testcase():
    data = "\n".join(map(str, numbers))
    sys.stdout.write(f"{len(numbers)}\n{data}\n")
    sys.stdout.flush()
    os.close(sys.stdout.fileno())


print_thread = threading.Thread(target=print_testcase, daemon=True)
print_thread.start()

expected = sum(numbers)

try:
    team_ans_string = sys.stdin.readline()
    try:
        team_ans = int(team_ans_string)
    except ValueError:
        wrong_answer(f"team output '{team_ans_string}' is not an integer")
except EOFError:
    wrong_answer("no input from team")

if team_ans != expected:
    wrong_answer(f"got {team_ans}, expected {expected}")

try:
    more_input = "".join(sys.stdin.readlines())
    if more_input and not more_input.isspace():
        wrong_answer(f'extra input from team, starting with "{more_input}"')
except EOFError:
    pass

sys.exit(42)  # AC
