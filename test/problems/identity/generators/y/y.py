#!/usr/bin/env python3
import sys
import random
import pathlib

# Seed with the directory name.
random.seed(pathlib.Path(sys.argv[0]).parts[-2])
print(random.randint(0, 1000))
