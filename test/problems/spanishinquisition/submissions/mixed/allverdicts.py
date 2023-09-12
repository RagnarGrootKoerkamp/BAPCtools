#! /usr/bin/env python3
""" This submission produces get *all* verdicts on various inputs."""

x, y = map(int, input().split())
result = 0
while (x + y) // 2 != result // 2: # WA if result is odd
    result += 1
# TLE if result is negative
assert result != 0 # RTEs for result 0
print(result)
