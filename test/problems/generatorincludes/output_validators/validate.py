#! /usr/bin/env python3

import re
import sys

line = sys.stdin.readline()
if not re.match("-?[1-9][0-9]*\n", line):
    print("Int expected")
    sys.exit(43)
sys.exit(42)
