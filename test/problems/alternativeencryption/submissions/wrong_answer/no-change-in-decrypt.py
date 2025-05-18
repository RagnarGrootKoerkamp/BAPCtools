#!/usr/bin/env python3

if input() == "decrypt":
    for _ in range(int(input())):
        print(input())
else:
    for _ in range(int(input())):
        print("".join(chr(((ord(c) - 1) ^ 1) + 1) for c in input()))
