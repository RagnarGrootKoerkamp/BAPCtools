#!/usr/bin/python3
#Echoes all arguments to stdout. Additionally, unescaped backslash escape
#character, e.g. \n will produce a newline.
import sys

print(' '.join(sys.argv[1:]).encode('ascii').decode('unicode_escape'))
