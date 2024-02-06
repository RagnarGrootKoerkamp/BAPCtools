#! /usr/bin/env python3

import sys

with open(sys.argv[1]) as infile:
    for _ in range(int(infile.readline())):
        line = sys.stdin.readline()
        try:
            x = float(line)
        except ValueError:
            print("Float expected", file=sys.stderr)
            sys.exit(43)
if not sys.stdin.readline() == "":
    sys.exit(43)
sys.exit(42)
