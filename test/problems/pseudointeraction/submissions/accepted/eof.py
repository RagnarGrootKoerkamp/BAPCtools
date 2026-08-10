#!/usr/bin/env python3
input()
ans = 0
while True:
    try:
        ans += int(input())
    except EOFError:
        break
print(ans)
