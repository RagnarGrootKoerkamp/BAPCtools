import sys
import random
import pathlib
# Seed with the directory name.
random.seed(pathlib.Path(sys.argv[0]).parts[-1])
print(random.randint(0, 1000))
