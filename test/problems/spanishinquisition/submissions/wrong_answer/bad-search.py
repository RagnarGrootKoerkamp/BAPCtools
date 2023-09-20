#! /usr/bin/env python3

x, y = map(int, input().split())

result = 0
while result != x + y:
    result += 1
print(result)
