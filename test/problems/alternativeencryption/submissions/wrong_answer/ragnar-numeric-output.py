#!/usr/bin/env python3

mode = input()
n = int(input())


def rot(x):
    return chr(ord("a") + (ord(x) - ord("a") + 13) % 26)


for i in range(n):
    word = input()
    out = list(rot(x) for x in word)
    if i == 0:
        out[0] = "0"
    print(*out, sep="")
