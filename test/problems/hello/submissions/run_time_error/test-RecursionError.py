#!/usr/bin/env python3
import sys

sys.setrecursionlimit(1024)


def hello(depth):
    return "Hello world!" if depth == 0 else hello(depth - 1)


print(hello(10**7))
