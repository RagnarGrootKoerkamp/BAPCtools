#!/usr/bin/env python3
# fmt: off
import sys

for line in sys.stdin:
    ab = line.split()
    a = int(ab[0])
    b = int(ab[1])
    print(abs(a-b))
# fmt: on
