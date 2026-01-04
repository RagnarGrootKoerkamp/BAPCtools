#! /usr/bin/env python3

import re
import sys

line = sys.stdin.readline()
if not re.match(r"(-?[1-9][0-9]*|0)\n", line):
    sys.exit(43)
sys.exit(42)
