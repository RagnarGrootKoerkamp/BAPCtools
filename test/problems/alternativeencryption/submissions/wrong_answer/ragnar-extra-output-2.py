#!/usr/bin/env python3

mode = input()
n = int(input())


def rot(x):
    return chr(ord("a") + (ord(x) - ord("a") + 13) % 26)


for _ in range(n):
    word = input()
    print(*(rot(x) for x in word), sep="")


print("extra")
