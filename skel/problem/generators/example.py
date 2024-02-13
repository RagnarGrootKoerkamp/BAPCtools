#!/usr/bin/python3
import sys
import random

#Init seed with first argument
random.seed(int(sys.argv[1]))

#Read the second... arguments and evaluate them as python. Example call:
#example.py {seed} list(range(3,6)) + [2**i for i in range(5)]
# =>               [3, 4, 5]        + [1, 2, 4, 8, 16]
list = eval(' '.join(sys.argv[2:]).encode('ascii').decode('unicode_escape'))

#Shuffle the list
random.shuffle(list)

#Print in default format i.e. one line with the number of elements and then 
#the space separated elements 
print(len(list))
print(*list)
