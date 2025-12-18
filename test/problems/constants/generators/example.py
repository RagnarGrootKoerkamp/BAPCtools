#!/usr/bin/python3
import sys

values = sys.argv[1:] + ["{{FIVE}}", "{{FIVE.value}}", "{{FIVE.INT}}", "{{FIVE.STRING}}", "5"]
assert len(set(values)) == 1
print(values[0])
