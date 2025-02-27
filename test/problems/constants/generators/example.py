#!/usr/bin/python3
import sys

if len(sys.argv) > 1:
    sys.argv[1].startswith("{{")
    sys.argv[1].endswith("}}")
print("{{INT_FIVE}}")
