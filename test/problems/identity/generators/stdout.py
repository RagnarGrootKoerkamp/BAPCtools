#!/usr/bin/env python3
import sys

print(sys.argv[1])
if len(sys.argv) > 2:
    print(sys.argv[2], file=sys.stderr)
