#!/usr/bin/env python3

print(" ")
input()
print()
for _ in range(int(input())):
    print("".join(chr(((ord(c) - 1) ^ 1) + 1) for c in input()) + " ")
    print()
    print(" ")
print(" ")
print()
