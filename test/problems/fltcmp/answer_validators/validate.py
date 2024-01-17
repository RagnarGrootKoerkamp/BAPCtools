#! /usr/bin/env python3

import sys

for line in sys.stdin:
    try:
        x = float(line)
    except ValueError:
        print("Float expected", file=sys.stderr)
        sys.exit(43)
sys.exit(42)
