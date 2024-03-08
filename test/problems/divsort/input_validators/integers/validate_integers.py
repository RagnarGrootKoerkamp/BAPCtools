#!/usr/bin/env python3

import sys

line = sys.stdin.readline()
if not len(line.split()) == 4:
    print("Expected 4 tokens, got {len(line.split())}", file=sys.stderr)
    sys.exit(43)
a, b, _, _= line.split()

if '--integer' in sys.argv[1:]:
    if float(a) != int(float(a)) or float(b) != int(float(b)):
        print("Failed to convert {a} and {b} to integers", file=sys.stderr)
        sys.exit(43)
if 'small' in sys.argv[1:]:
    if max(float(a), float(b)) > 100:
        print(f"Expected small numbers, got {a} and {b}", file=sys.stderr)
        sys.exit(43)
sys.exit(42)
