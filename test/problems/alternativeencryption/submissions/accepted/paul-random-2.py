#!/usr/bin/env python3
import random

random.seed(987)

perms = []
for _ in range(111):
    perm = list(range(26))
    while any(i == j for i, j in enumerate(perm)):
        random.shuffle(perm)
    perms.append(perm)

if input() == "decrypt":
    inv_perms = []
    for perm in perms:
        inv_perm = [None] * 26
        for i, j in enumerate(perm):
            inv_perm[j] = i
        inv_perms.append(inv_perm)
    perms = inv_perms

for _ in range(int(input())):
    s = input()
    print("".join(chr(ord("a") + perms[len(s)][ord(c) - ord("a")]) for c in s))
