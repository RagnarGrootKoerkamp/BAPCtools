#!/usr/bin/env python3
import random
import sys

maxlen = 100

random.seed(int(sys.argv[1]))


def letter(i):
    return chr(ord("a") + i)


def randomstring(len):
    letters = [letter(random.randint(0, 25)) for _ in range(len)]
    string = "".join(letters)
    return string


strings = []

# Single letter
strings.extend(letter(i) for i in range(0, 26))

# Fixed strings
strings.append("aaaaaaaaaa")
strings.append("abcdefghijklmnopqrstuvwxyz")
strings.append("dejavu")
strings.append("dejavu")
strings.append("dejavu")

# Random strings, random length
for _ in range(100):
    n = random.randint(10, maxlen)
    strings.append(randomstring(n))

# Random strings, max length
strings.extend(randomstring(maxlen for _ in range(20)))


# Print strings
print(len(strings))
for string in strings:
    print(string)
