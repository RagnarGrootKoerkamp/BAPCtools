#! /usr/bin/env python3
""" Irrationally afraid of 13, and (as expected)
    fails on corresponding inputs. However,
    also (unexpectedly) fails on 14.
"""

x, y = map(int, input().split())
result = x + y
if 12 < result < 15:
    print(12)
else:
    print(result)
