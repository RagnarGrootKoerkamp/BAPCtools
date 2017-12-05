#!/usr/bin/python3
"""
make a zip for each problem in the contest
call with 1 contest parameter
./tools/make_all_domjudge_zips.py <contest>
"""

from make_domjudge_zip import make_domjudge_zip 
from tools import get_problems, sort_problems
import sys
import os
import yaml
import glob

def main():
    assert(len(sys.argv) == 2)
    contest = sys.argv[1]
    problems = sort_problems(get_problems(contest)[0])
    # for testsessions, start at X
    for problem in problems:
        print("PROBLEM",problem)
        make_domjudge_zip(problem[0], problem[1]+'.zip')

if __name__ == '__main__':
    main()

