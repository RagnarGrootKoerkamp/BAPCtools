#!/usr/bin/env python3
import time

mode = input()
n = int(input())


def rot(x):
    return chr(ord("a") + (ord(x) - ord("a") + 13) % 26)


for _ in range(n):
    word = input()
    print(*(rot(x) for x in word), sep="")

current_time = time.time()
while time.time() < current_time + 0.75:
    pass
