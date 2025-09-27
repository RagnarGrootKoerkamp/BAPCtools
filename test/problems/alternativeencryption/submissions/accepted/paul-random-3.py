#!/usr/bin/env python3
import random

random.seed(987)

perms = []
for n in range(111):
    perms.append([])
    for _ in range(n):
        perm = list(range(26))
        while any(i == j for i, j in enumerate(perm)):
            random.shuffle(perm)
        perms[-1].append(perm)

if input() == "decrypt":
    inv_perms = []
    for row in perms:
        inv_perms.append([])
        for perm in row:
            inv_perm = [None] * 26
            for i, j in enumerate(perm):
                inv_perm[j] = i
            inv_perms[-1].append(inv_perm)
    perms = inv_perms

for _ in range(int(input())):
    s = input()
    print("".join(chr(ord("a") + perms[len(s)][i][ord(c) - ord("a")]) for i, c in enumerate(s)))
