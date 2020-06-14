import re

import validate

# Local imports
from util import *

"""DISCLAIMER:

  This tool was only made to check constraints faster.
  However it is not guaranteed it will find all constraints.
  Checking constraints by yourself is probably the best way.
"""


def check_constraints(problem, settings):
    problem.validate_format('input_format', check_constraints=True)
    problem.validate_format('output_format', check_constraints=True)

    vinput = problem.path / 'input_validators/input_validator/input_validator.cpp'
    voutput = problem.path / 'output_validators/output_validator/output_validator.cpp'

    cpp_statement = [
        (re.compile(
            '^(const\s+|constexpr\s+)?(int|string|long long|float|double)\s+(\w+)\s*[=]\s*(.*);'),
         3, 4, None),
        (re.compile(
            '(?:(\w*)\s*=\s*.*)?\.read_(?:string|long_long|int|double|long_double)\((?:\s*([^,]+)\s*,)?\s*([0-9-e.,\']+)\s*[,\)]'
        ), 1, 2, 3),
    ]

    defs_validators = []
    for validator in [vinput, voutput]:
        print(validator)
        if not validator.is_file():
            warn(f'{print_name(validator)} does not exist.')
            continue
        with open(validator) as file:
            for line in file:
                for r, name, v1, v2 in cpp_statement:
                    mo = r.search(line)
                    if mo is not None:
                        if mo.group(v1) is not None:
                            defs_validators.append([mo.group(name) or '', mo.group(v1)])
                        if v2 is not None and mo.group(v2) is not None:
                            defs_validators.append([mo.group(name) or '', mo.group(v2)])

    statement = problem.path / 'problem_statement/problem.en.tex'
    #latex_define = re.compile('^\\newcommand{\\\\(\w+)}{(.*)}$')
    latex_defines = [
        (re.compile('{\\\\(\w+)}{(.*)}'), 1, 2, False),
        (re.compile('([0-9-e,.^]+)\s*(?:\\\\leq|\\\\geq|\\\\le|\\\\ge|<|>|=)\s*(\w*)'), 2, 1,
         True),
        (re.compile('(\w*)\s*(?:\\\\leq|\\\\geq|\\\\le|\\\\ge|<|>|=)\s*([0-9-e,.^]+)'), 1, 2,
         True),
    ]

    defs_statement = []
    input_output = False
    with open(statement) as file:
        for line in file:
            for r, name, value, io_only in latex_defines:
                if 'begin{Input}' in line:
                    input_output = True
                if 'end{Input}' in line:
                    input_output = False
                if 'begin{Output}' in line:
                    input_output = True
                if 'end{Output}' in line:
                    input_output = False
                if io_only and not input_output:
                    continue

                mo = r.search(line)
                if mo is not None:
                    mo = r.search(line)
                    if mo is not None:
                        if mo.group(value) is not None:
                            defs_statement.append([mo.group(name) or '', mo.group(value)])

    # print all the definitions.
    nl = len(defs_validators)
    nr = len(defs_statement)

    print('{:^30}|{:^30}'.format('  VALIDATORS', '      PROBLEM STATEMENT'), sep='')
    for i in range(0, max(nl, nr)):
        if i < nl:
            print('{:>15}  {:<13}'.format(defs_validators[i][0], defs_validators[i][1]),
                  sep='',
                  end='')
        else:
            print('{:^30}'.format(''), sep='', end='')
        print('|', end='')
        if i < nr:
            print('{:>15}  {:<13}'.format(defs_statement[i][0], defs_statement[i][1]),
                  sep='',
                  end='')
        else:
            print('{:^30}'.format(''), sep='', end='')
        print()

    return True
