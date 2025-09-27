#!/usr/bin/env python3
import random

perm = list(range(26))
while any(i == j for i, j in enumerate(perm)):
    random.shuffle(perm)

if input() == "decrypt":
    inv_perm = [None] * 26
    for i, j in enumerate(perm):
        inv_perm[j] = i
    perm = inv_perm

for _ in range(int(input())):
    s = input()
    print("".join(chr(ord("a") + perm[ord(c) - ord("a")]) for c in s))
