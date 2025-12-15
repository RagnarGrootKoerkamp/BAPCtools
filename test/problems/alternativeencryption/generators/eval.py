#!/usr/bin/python3
import sys
from random import choice, randrange, seed
from string import ascii_lowercase as sigma

# to make ruff happy
randrange(1, 2)


def randstr(n):
    return "".join([choice(sigma) for _ in range(n)])


# Init seed with first argument
seed(int(sys.argv[1]))
n = int(sys.argv[2])
command = " ".join(sys.argv[3:]).encode("ascii").decode("unicode_escape")

print("encrypt")
print(n)
for i in range(n):
    print(eval(command))
