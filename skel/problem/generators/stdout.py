#!/usr/bin/python3
import sys

print(' '.join(sys.argv[1:]).encode('ascii').decode('unicode_escape'))
