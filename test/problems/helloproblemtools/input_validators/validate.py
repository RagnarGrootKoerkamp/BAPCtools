#!/usr/bin/env python3
import sys

# The input should be ``Hello``
assert sys.stdin.readline() == "Hello!\n"
assert len(sys.stdin.readline()) == 0

sys.exit(42)
