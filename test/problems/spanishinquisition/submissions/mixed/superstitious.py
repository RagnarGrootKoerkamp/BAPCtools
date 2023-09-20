#! /usr/bin/env python3
""" Irrationally afraid of the integer between 12 and 14 and therefore fails on
    inputs where that's the correct answer.
"""

x, y = map(int, input().split())
result = x + y
if 12 < result < 14:
    print(12)
else:
    print(result)
