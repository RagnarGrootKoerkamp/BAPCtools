#!/usr/bin/env python3
#
# Testing tool for the XXX problem  # TODO update name
#
# Usage:
#
#   python3 testing_tool.py -f inputfile <program invocation>
#
#
# Use the -f parameter to specify the input file, e.g. 1.in.
# The input file should contain three lines:
# - The first line contains the width and height of the image.
# - The second and third line each contain the coordinates of one point on the horizon.

# You can compile and run your solution as follows:

# C++:
#   g++ solution.cpp
#   python3 testing_tool.py -f 1.in ./a.out

# Python:
#   python3 testing_tool.py -f 1.in python3 ./solution.py

# Java:
#   javac solution.java
#   python3 testing_tool.py -f 1.in java solution

# Kotlin:
#   kotlinc solution.kt
#   python3 testing_tool.py -f 1.in kotlin solutionKt


# The tool is provided as-is, and you should feel free to make
# whatever alterations or augmentations you like to it.
#
# The tool attempts to detect and report common errors, but it is not an exhaustive test.
# It is not guaranteed that a program that passes this testing tool will be accepted.


import argparse
import subprocess
import traceback

parser = argparse.ArgumentParser(description="Testing tool for problem XXX.")  # TODO update name
parser.add_argument(
    "-f",
    dest="inputfile",
    metavar="inputfile",
    default=None,
    type=argparse.FileType("r"),
    required=True,
    help="The input file to use.",
)
parser.add_argument("program", nargs="+", help="Invocation of your solution")

args = parser.parse_args()

with (
    args.inputfile as f,
    subprocess.Popen(
        " ".join(args.program),
        shell=True,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        universal_newlines=True,
    ) as p,
):
    assert p.stdin is not None and p.stdout is not None
    p_in = p.stdin
    p_out = p.stdout

    def write(line: str):
        assert p.poll() is None, "Program terminated early"
        print(f"Write: {line}", flush=True)
        p_in.write(f"{line}\n")
        p_in.flush()

    def read() -> str:
        assert p.poll() is None, "Program terminated early"
        line = p_out.readline().strip()
        assert line != "", "Read empty line or closed output pipe"
        print(f"Read: {line}", flush=True)
        return line

    # Parse input
    lines = f.readlines()
    w, h = map(int, lines[0].split())
    p0 = list(map(int, lines[1].split()))
    p1 = list(map(int, lines[2].split()))

    def point_type(x: int, y: int):
        d = (p0[0] - x) * (p1[1] - y) - (p0[1] - y) * (p1[0] - x)
        if d == 0:
            return "horizon"
        if d > 0:
            return "sky"
        if d < 0:
            return "sea"
        assert False

    # Simulate interaction
    try:
        write(f"{w} {h}")
        queries = 0
        while True:
            line = read().split()
            if line[0] == "?":
                queries += 1
                x, y = map(int, line[1:])
                assert 1 <= x <= w, "Point not in bounds"
                assert 1 <= y <= h, "Point not in bounds"
                write(point_type(x, y))
            elif line[0] == "!":
                x1, y1, x2, y2 = map(int, line[1:])
                assert 1 <= x1 <= w, "Point not in bounds"
                assert 1 <= y1 <= h, "Point not in bounds"
                assert 1 <= x2 <= w, "Point not in bounds"
                assert 1 <= y2 <= h, "Point not in bounds"
                assert (x1, y1) != (x2, y2)
                assert point_type(x1, y1) == "horizon", "First point does not lie on the horizon"
                assert point_type(x2, y2) == "horizon", "First point does not lie on the horizon"
                break
            else:
                assert False, "Line does not start with question or exclamation mark"

        print()
        print(f"Found a valid solution: ({x1}, {y1}) and ({x2}, {y2})")
        print(f"Queries used: {queries}", flush=True)
        assert (extra := p_out.readline()) == "", (
            f"Your submission printed extra data after finding a solution: '{extra[:100].strip()}{'...' if len(extra) > 100 else ''}'"
        )
        print(f"Exit code: {p.wait()}", flush=True)
        assert p.wait() == 0, "Your submission did not exit cleanly after finishing"

    except AssertionError as e:
        print()
        print(f"Error: {e}")
        print()
        print("Killing your submission.", flush=True)
        p.kill()
        exit(1)

    except Exception:
        print()
        print("Unexpected error:")
        traceback.print_exc()
        print()
        print("Killing your submission.", flush=True)
        p.kill()
        exit(1)
