import re
import itertools
import sys

import validate
from colorama import Fore, Style

# Local imports
from util import *

"""DISCLAIMER:

  This tool was only made to check constraints faster.
  However it is not guaranteed it will find all constraints.
  Checking constraints by yourself is probably the best way.
"""


def check_validators(problem):
    in_constraints = {}
    ans_constraints = {}
    problem.validate_data(validate.Mode.INPUT, constraints=in_constraints)
    if not in_constraints:
        warn("No constraint validation of input values found in input validators.")
    problem.validate_data(validate.Mode.ANSWER, constraints=ans_constraints)
    if not problem.interactive and not problem.multipass and not ans_constraints:
        log("No constraint validation of answer values found in answer or output validators.")
    print()

    validator_values = set()
    validator_defs = []

    def f(cs):
        for loc, value in sorted(cs.items()):
            name, has_low, has_high, vmin, vmax, low, high = value
            validator_defs.append([low, name, high])
            validator_values.add(low)
            validator_values.add(high)

    f(in_constraints)
    validator_defs.append('')
    validator_defs.append('OUTPUT')
    f(ans_constraints)

    return validator_values, validator_defs


def check_statement(problem, language):
    statement_file = problem.path / f'problem_statement/problem.{language}.tex'
    statement = statement_file.read_text()

    statement_values = set()
    statement_defs = []

    defines = ['\\def', '\\newcommand']
    sections = ['Input', 'Output', 'Interaction']
    maths = [('$', '$'), ('\\(', '\\)')]
    commands = {
        'leq': '<=',
        'le': '<=',
        'ge': '>=',
        'geq': '>=',
        #'eq' : '=',
        'neq': '!=',
        'cdot': '*',
        'ell': 'l',
    }
    relations = re.compile(r'(<=|!=|>=|<|=|>)')

    def math_eval(text):
        try:
            # eval is dangerous, but on the other hand we run submission code so this is fine
            text = text.replace('^', '**')
            return eval(text, {'__builtin__': None})
        except (SyntaxError, NameError, TypeError, ZeroDivisionError) as e:
            return None

    def constraint(text):
        # handles $$math$$
        if len(text) == 0:
            return
        # remove unnecessary whitespaces
        text = ' '.join(text.split())
        # evaluate known commands (flat)
        for key in commands:
            text = text.replace(f'\\{key}', commands[key])
        # substitute more known math
        text = re.sub(r'\\frac{(.*)}{(.*)}', r'(\1)/(\2)', text)
        text = text.replace('\\,', '')
        text = text.replace('{}', ' ')
        text = text.replace('{', '(')
        text = text.replace('}', ')')
        text = re.sub(r'(\d)\(', r'\1*(', text)
        text = re.sub(r'\)(\d)', r')*\1', text)

        # remove outer most parenthesis if they exist
        # allows $(constraint)$ and ($constraint$)
        if text[0] == '(' and text[-1] == ')':
            cur = 0
            neg = False
            for c in text[1:-1]:
                if c == '(':
                    cur += 1
                elif c == ')':
                    cur -= 1
                neg |= cur < 0
            if not neg:
                text = text[1:-1]

        # a constraint must contain at least one relation
        parts = relations.split(text)
        if len(parts) != 1:
            for i, p in enumerate(parts):
                # eval parts to get numbers if possible
                tmp = math_eval(p)
                if tmp is not None:
                    statement_values.add(tmp)
                    parts[i] = str(tmp)
                else:
                    parts[i] = parts[i].strip()
            # join back together with single paces
            statement_defs.append(' '.join(parts))

    # parse a flat latex structure (does not handle nested environments)
    pos = 0
    in_io = False
    end = None

    def matches(text):
        nonlocal pos
        if pos + len(text) > len(statement):
            return False
        return statement[pos : pos + len(text)] == text

    def parse_group():
        nonlocal pos
        assert statement[pos] == '{'
        next = pos + 1
        depth = 1
        while next < len(statement) and depth > 0:
            if statement[next] == '{':
                depth += 1
            elif statement[next] == '}':
                depth -= 1
            next += 1
        if depth != 0:
            next += 1
        name = statement[pos + 1 : next - 1]
        pos = next
        return name

    def parse_command():
        nonlocal pos
        assert statement[pos] == '\\'
        next = pos + 1
        while next < len(statement) and statement[next] != '\\' and statement[pos] != '{':
            next += 1
        name = statement[pos + 1 : next]
        pos = next
        return name

    # parse by priority:
    # 1) if a comment starts skip to end of line
    # 2) if an environment ends parse that
    # 3) if a section starts parse that (and ensure that no environment is active)
    # 4) if an environment begins parse that (and ensure that no other environment is active)
    # 5) if a new define starts parse that
    # 6) if inline math starts in an input/ouput part parse it as constraint
    while pos < len(statement):
        if statement[pos] == '%':
            next = statement.find('\n', pos)
            pos = next + 1 if pos < next else len(statement)
        elif end is not None and matches(end):
            pos += len(end)
            end = None
            in_io = False
        elif matches('\\begin{'):
            for section in sections:
                if matches(f'\\begin{{{section}}}'):
                    # io environments should not be nested
                    if end is not None:
                        error(f'Unexpected "\\begin{{{section}}}" in {statement_file.name}!')
                        return statement_values, statement_defs
                    pos += 8 + len(section)
                    end = f'\\end{{{section}}}'
                    in_io = True
                    break
            else:
                pos += 7
        elif matches('\\section{') or matches('\\section*{'):
            # no section should start inside an io environment
            if end is not None:
                error(f'Unexpected "\\section" in {statement_file.name}!')
                return statement_values, statement_defs
            in_io = False
            for section in sections:
                if matches(f'\\section{{{section}}}'):
                    pos += 10 + len(section)
                    in_io = True
                    break
                elif matches(f'\\section*{{{section}}}'):
                    pos += 11 + len(section)
                    in_io = True
                    break
            else:
                pos += 9
        else:
            for define in defines:
                if matches(define + '{'):
                    pos += len(define)
                    name = parse_group()
                elif matches(define + '\\'):
                    pos += len(define)
                    name = parse_command()
                else:
                    continue
                if matches('{'):
                    value = parse_group()
                elif matches('\\'):
                    value = parse_command()
                else:
                    error(f'Could not parse "{define}{{{name}}}[...]"!')
                    return statement_values, statement_defs
                for key in commands:
                    value = value.replace(f'\\{key}', commands[key])
                commands[name[1:]] = value
                break
            else:
                if in_io:
                    # only parse math in specified sections
                    for b, e in maths:
                        if matches(b):
                            next = statement.find(e, pos + len(b))
                            if next > pos:
                                constraint(statement[pos + len(b) : next])
                                pos = next + len(e)
                                break
                    else:
                        pos += 1
                else:
                    pos += 1
    # ensure that environment was closed
    if end is not None:
        error(f'Missing "{end}" in {statement_file.name}!')
    return statement_values, statement_defs


def check_constraints(problem):
    validator_values, validator_defs = check_validators(problem)
    statement_values = {}
    statement_defs = {}
    for lang in problem.statement_languages:
        values, defs = check_statement(problem, lang)
        for entry in values:
            statement_values.setdefault(entry, set())
            statement_values[entry].add(lang)
        for entry in defs:
            statement_defs.setdefault(entry, set())
            statement_defs[entry].add(lang)

    # print all the definitions.
    value_len = 12
    name_len = 8
    left_width = 8 + name_len + 2 * value_len

    print(
        '{:^{width}}|{:^40}'.format('VALIDATORS', 'PROBLEM STATEMENT', width=left_width),
        sep='',
    )

    while statement_defs or validator_defs:
        # print(statement_defs, validator_defs)
        if statement_defs:
            # Display constraints in the order they appear in statement (statement_defs is thus ordered)
            st = next(iter(statement_defs))
            # Find a validator_def matching st, if there is one
            val = min((d for d in validator_defs if len(d) == 3 and d[1] in st), default=None)
        else:
            # No statement_defs left? Just take the next validator_def
            st = None
            val = validator_defs[0]

        if val is not None:
            validator_defs.remove(val)
            if isinstance(val, str):
                print('{:^{width}}'.format(val, width=left_width), sep='', end='')
            else:
                print(
                    '{:>{value_len}} <= {:^{name_len}} <= {:<{value_len}}'.format(
                        *val, name_len=name_len, value_len=value_len
                    ),
                    sep='',
                    end='',
                )
        else:
            print('{:^{width}}'.format('', width=left_width), sep='', end='')
        print('|', end='')
        if st is not None:
            languages = ','.join(statement_defs[st])
            print('{:^40} {}'.format(st, languages), sep='', end='')
        else:
            print('{:^40}'.format(''), sep='', end='')
        print()
        if st is not None:
            statement_defs.pop(st)

    print()

    warned = False
    for value in validator_values:
        languages = statement_values.get(value, set())
        missing = sorted(set(problem.statement_languages) - languages)
        if len(missing) > 0:
            if not warned:
                warned = True
                warn('Values in validators but missing in some statement:')
            print(f'{Fore.YELLOW}{value}{Style.RESET_ALL} missing in', ','.join(missing))

    extra_in_statement = set(statement_values.keys()).difference(validator_values)
    if extra_in_statement:
        warn('Values in some statement but not in input validators:')
        for value in extra_in_statement:
            print(
                f'{Fore.YELLOW}{value}{Style.RESET_ALL} in',
                ','.join(sorted(statement_values[value])),
            )

    return True
