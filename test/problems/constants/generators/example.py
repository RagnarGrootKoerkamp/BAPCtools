#!/usr/bin/python3
import sys

values = sys.argv[1:] + ["{{INT_FIVE}}", "{{STRING_FIVE}}", "5"]
assert len(set(values)) == 1
print(values[0])
