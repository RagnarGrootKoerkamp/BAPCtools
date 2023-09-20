#! /usr/bin/env python3

import sys

line = input().split()

try:
    x = int(line[0])
    y = int(line[1])
except ValueError:
    sys.exit(43)
sys.exit(42)
