import re
import itertools

import validate

# Local imports
from util import *
"""DISCLAIMER:

  This tool was only made to check constraints faster.
  However it is not guaranteed it will find all constraints.
  Checking constraints by yourself is probably the best way.
"""


def check_constraints(problem, settings):
    in_constraints = {}
    ans_constraints = {}
    problem.validate_format('input_format', constraints=in_constraints)
    problem.validate_format('output_format', constraints=ans_constraints)
    print()

    vinput = problem.path / 'input_validators/input_validator/input_validator.cpp'
    voutput = problem.path / 'output_validators/output_validator/output_validator.cpp'

    cpp_statement = [
        (re.compile(
            r'^(const\s+|constexpr\s+)?(int|string|long long|float|double)\s+(\w+)\s*[=]\s*(.*);'),
         3, 4, None),
        (re.compile(
            r'(?:(\w*)\s*=\s*.*)?\.read_(?:number|integer|float|string|long_long|int|double|long_double)\((?:\s*([^,]+)\s*,)?\s*([0-9-e.,\']+)\s*[,\)]'
        ), 1, 2, 3),
    ]

    validator_values = set()
    defs_validators = []
    def f(cs):
        for loc, value in sorted(cs.items()):
            name, has_low, has_high, vmin, vmax, low, high = value
            defs_validators.append([low, name, high])
            validator_values.add(eval(low))
            validator_values.add(eval(high))

    f(in_constraints)
    defs_validators.append('')
    defs_validators.append('OUTPUT')
    f(ans_constraints)


    statement = problem.path / 'problem_statement/problem.en.tex'
    latex_defines = [
        (re.compile(r'(?:new|command|define).*{\\(\w+)}{(.*)}'), 1, 2, False),
        (re.compile(r'\$(.*(?:\\leq|\\geq|\\le|\\ge|<|>|=).*)\$'), 1, None, True),
        (re.compile(r'(-?\d[{}\d,.\-^]*)'), None, 1, True),
    ]

    statement_values = set()
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
                        name_string = None
                        if name: name_string = mo.group(name) or ''

                        value_string = None
                        if value is not None and mo.group(value) is not None:
                            value_string = mo.group(value)
                            eval_string = value_string
                            eval_string = re.sub(r'\\frac{(.*)}{(.*)}', r'(\1)/(\2)', eval_string)
                            eval_string = eval_string.replace('^', '**')
                            eval_string = eval_string.replace('{,}', '')
                            eval_string = eval_string.replace('\\,', '')
                            eval_string = eval_string.replace(',', '')
                            eval_string = eval_string.replace('{', '(')
                            eval_string = eval_string.replace('}', ')')
                            eval_string = eval_string.replace('\\cdot', '*')
                            try:
                                val = eval(eval_string)
                                statement_values.add(eval(eval_string))
                            except (SyntaxError, NameError) as e:
                                log(f'SyntaxError for {value_string} when trying to evaluate {eval_string} ')
                                log(str(e))

                        l = []
                        if name_string: l.append(name_string)
                        if value_string: l.append(value_string)
                        defs_statement.append(l)
    defs_statement.sort()

    # print all the definitions.
    value_len = 12
    name_len = 8
    left_width = 8 + name_len + 2*value_len

    print('{:^{width}}|{:^30}'.format('VALIDATORS', '      PROBLEM STATEMENT', width=left_width), sep='')
    for val, st in itertools.zip_longest(defs_validators, defs_statement):
        if val is not None:
            if isinstance(val, str):
                print('{:^{width}}'.format(val, width=left_width), sep='',end='')
            else:
                print('{:>{value_len}} <= {:^{name_len}} <= {:<{value_len}}'.format(*val, name_len=name_len,value_len=value_len),
                  sep='',
                  end='')
        else:
            print('{:^{width}}'.format('', width=left_width), sep='', end='')
        print('|', end='')
        if st is not None:
            if len(st) == 2:
                print('{:>15}  {:<13}'.format(*st), sep='', end='')
            else:
                print('{:^30}'.format(*st), sep='', end='')
        else:
            print('{:^30}'.format(''), sep='', end='')
        print()

    print()

    extra_in_validator = validator_values.difference(statement_values)
    if extra_in_validator:
        warn('Values in validators but not in statement:')
        for v in extra_in_validator:
            print(v)
    extra_in_statement = statement_values.difference(validator_values)
    if extra_in_validator:
        warn('Values in statement but not in input validators:')
        for v in extra_in_statement:
            print(v)

    return True
