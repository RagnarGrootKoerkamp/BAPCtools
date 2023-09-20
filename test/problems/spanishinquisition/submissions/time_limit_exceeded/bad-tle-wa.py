#! /usr/bin/env python3
""" This is wrong exactly when the two inputs are different and runs
    forever exactly if the sum is negative.
"""

inputs = set(map(int, input().split()))
result = 0
while result != sum(inputs):
    result += 1
print(result)
