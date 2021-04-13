#!/usr/bin/env python3
import sys
import random

random.seed(sys.argv[1])
print(random.randint(0, 1000))
