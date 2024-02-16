#!/usr/bin/env python3
#
# Testing tool for the XXX problem
#
# Usage:
#
#   python3 testing_tool.py -f inputfile <program invocation>
#
# Use the -f parameter to specify the input file, e.g. 1.in.
# The input file should contain three lines:
# - The first line contains the width and height of the image.
# - The second and third line each contain the coordinates of one point on the horizon.
#

# You can compile and run your solution as follows.
# - You may have to replace 'python3' by just 'python'.
# - On Windows, you may have to to replace '/' by '\'.

# C++:
#   g++ solution.cpp
#   python3 testing_tool.py -f 1.in ./a.out

# Java
#   javac solution.java
#   python3 testing_tool.py -f 1.in java solution

# Python3
#   python3 testing_tool.py -f 1.in python3 ./solution.py


# The tool is provided as-is, and you should feel free to make
# whatever alterations or augmentations you like to it.
#
# The tool attempts to detect and report common errors, but it is not an
# exhaustive test. It is not guaranteed that a program that passes this testing
# tool will be accepted.
#

import argparse
import subprocess
import traceback

import sys


def write(p, line):
    assert p.poll() is None, "Program terminated early"
    print("Write: {}".format(line), flush=True)
    p.stdin.write("{}\n".format(line))
    p.stdin.flush()


def read(p):
    assert p.poll() is None, "Program terminated early"
    line = p.stdout.readline().strip()
    assert line != "", "Read empty line or closed output pipe"
    print("Read: {}".format(line), flush=True)
    return line


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

with args.inputfile as f:
    lines = f.readlines()
    w, h = map(int, lines[0].split())
    p0 = list(map(int, lines[1].split()))
    p1 = list(map(int, lines[2].split()))


def type(x, y):
    d = (p0[0] - x) * (p1[1] - y) - (p0[1] - y) * (p1[0] - x)
    if d == 0:
        return "horizon"
    if d > 0:
        return "sky"
    if d < 0:
        return "sea"
    assert False


with subprocess.Popen(
    " ".join(args.program),
    shell=True,
    stdout=subprocess.PIPE,
    stdin=subprocess.PIPE,
    universal_newlines=True,
) as p:
    try:
        write(p, "{} {}".format(w, h))
        queries = 0
        while True:
            line = read(p).split()
            if line[0] == "?":
                queries += 1
                x, y = map(int, line[1:])
                assert 1 <= x and x <= w, "Point not in bounds"
                assert 1 <= y and y <= h, "Point not in bounds"
                write(p, type(x, y))
            elif line[0] == "!":
                x1, y1, x2, y2 = map(int, line[1:])
                assert 1 <= x1 and x1 <= w, "Point not in bounds"
                assert 1 <= y1 and y1 <= h, "Point not in bounds"
                assert 1 <= x2 and x2 <= w, "Point not in bounds"
                assert 1 <= y2 and y2 <= h, "Point not in bounds"
                assert (x1, y1) != (x2, y2)
                assert type(x1, y1) == "horizon", "First point does not lie on the horizon."
                assert type(x2, y2) == "horizon", "First point does not lie on the horizon."
                break
            else:
                assert False, "Line does not start with question or exclamation mark."

        assert (
            p.stdout.readline() == ""
        ), "Your submission printed extra data after finding a solution."
        assert p.wait() == 0, "Your submission did not exit cleanly after finishing."

        sys.stdout.write("\nSuccess.\nQueries used: {}\n".format(queries))
    except:
        print()
        traceback.print_exc()
        print()
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print("Killing your submission after 2 second timeout.")
            p.kill()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.stdout.write("Exit code: {}\n".format(p.wait()))
        sys.stdout.flush()
