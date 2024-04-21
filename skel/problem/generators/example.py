#!/usr/bin/python3
import random
import sys

# Init seed with first argument
random.seed(int(sys.argv[1]))

# Read the second... arguments as ints Example call:
# example.py {seed} 1 2 3 4
values = list(map(int, sys.argv[2:]))

# Shuffle the list
random.shuffle(values)

# Print in standard format, i.e. one line with the number of values,
# followed by the space-separated values.
print(len(values))
print(*values)
