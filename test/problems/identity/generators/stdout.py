#!/usr/bin/env python3
import sys

print(sys.argv[1])
if 2 < len(sys.argv):
	print(sys.argv[2], file=sys.stderr)
