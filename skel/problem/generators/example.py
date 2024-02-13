#!/usr/bin/python3
import sys
import random

# Init seed with first argument
random.seed(int(sys.argv[1]))

# Read the second... arguments as ints Example call:
# example.py {seed} 1 2 3 4
l = list(map(int, sys.argv[2:]))

# Shuffle the list
random.shuffle(l)

# Print in standard format, i.e. one line with the number of elements,
# followed by the space-separated elements.
print(len(l))
print(*l)
