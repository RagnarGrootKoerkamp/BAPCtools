#!/usr/bin/env python3
import random
import sys

random.seed(sys.argv[1])
print(random.randint(0, 1000))
