#!/usr/bin/env python3
from sys import stdin
import sys

# The input should be ``Hello``
assert stdin.readline() == 'Hello!\n'
assert len(stdin.readline()) == 0

sys.exit(42)
