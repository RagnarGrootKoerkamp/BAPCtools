#!/usr/bin/env python3
from pathlib import Path

mode = input()
n = int(input())


def rot(x):
    return chr(ord("a") + (ord(x) - ord("a") + 13) % 26)


words = []

for _ in range(n):
    word = input()
    words.append(word)
    print(*(rot(x) for x in word), sep="")

file = Path(".data")
if mode == "encrypt":
    file.write_text("\n".join(words))
if mode == "decrypt":
    words = file.read_text()
