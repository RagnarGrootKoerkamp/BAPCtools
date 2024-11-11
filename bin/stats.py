import shutil
import statistics
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from colorama import ansi, Fore, Style

import config
import generate
import program
from util import error, glob, exec_command

Selector = str | Callable | list[str] | list[Callable]


# This prints the number belonging to the count.
# This can be a red/white colored number, or Y/N
def _get_stat(count, threshold=True, upper_bound=None):
    if threshold is True:
        if count is None:
            return Fore.WHITE + ' ' + Style.RESET_ALL
        if count >= 1:
            return Fore.WHITE + 'Y' + Style.RESET_ALL
        else:
            return Fore.RED + 'N' + Style.RESET_ALL
    color = Fore.WHITE
    if upper_bound is not None and count > upper_bound:
        color = Fore.YELLOW
    if count < threshold:
        color = Fore.RED
    return color + str(count) + Style.RESET_ALL


def stats(problems):
    problem_stats(problems)
    if config.args.slides:
        slides_stats(problems)


def problem_stats(problems):
    stats: list[
        tuple[str, Selector] | tuple[str, Selector, int] | tuple[str, Selector, int, int]
    ] = [
        # Roughly in order of importance
        ('  time', lambda p: p.settings.timelimit, 0),
        ('yaml', 'problem.yaml'),
        ('tex', 'problem_statement/problem*.tex'),
        ('sol', 'problem_statement/solution*.tex'),
        ('  val: I', ['input_validators/*', 'input_format_validators/*']),
        ('A', ['answer_validators/*']),
        ('O', ['output_validators/*']),
        (
            '  sample',
            [lambda s: {x.stem for x in s if x.parts[2] == 'sample'}],
            2,
        ),
        (
            'secret',
            [lambda s: {x.stem for x in s if x.parts[2] == 'secret'}],
            30,
            100,
        ),
        (
            'bad',
            [
                lambda s: {
                    x.stem
                    for x in s
                    if x.parts[2] in ['invalid_inputs', 'invalid_answers', 'invalid_outputs', 'bad']
                }
            ],
            0,
        ),
        ('   AC', 'submissions/accepted/*', 3),
        (' WA', 'submissions/wrong_answer/*', 2),
        ('TLE', 'submissions/time_limit_exceeded/*', 1),
        ('subs', lambda p: len(glob(p.path, 'submissions/*/*')), 6),
    ]
    languages = {
        '  c(++)': ['C', 'C++'],
        'py': ['Python 2', 'Python 3', 'CPython 2', 'CPython 3'],
        'java': ['Java'],
        'kt': ['Kotlin'],
    }
    for column, names in languages.items():
        paths = []
        for config in program.languages().values():
            if config['name'] in names:
                globs = config['files'].split() or []
                paths += [f'submissions/accepted/{glob}' for glob in globs]
        stats.append((column, list(set(paths)), 1))

    headers = ['problem', *(h[0] for h in stats), '   comment']
    cumulative = [0] * (len(stats))

    header_string = ''
    format_string = ''
    for header in headers:
        if header == 'problem':
            width = len(header)
            for problem in problems:
                width = max(width, len(problem.label + ' ' + problem.name))
            header_string += '{:<' + str(width) + '}'
            format_string += '{:<' + str(width) + '}'
        elif header == '  comment':
            header_string += '{}'
            format_string += '{}'
        else:
            width = len(header)
            header_string += ' {:>' + str(width) + '}'
            format_string += ' {:>' + str(width + len(Fore.WHITE) + len(Style.RESET_ALL)) + '}'

    header = header_string.format(*headers)
    print(Style.BRIGHT + header + Style.RESET_ALL, file=sys.stderr)

    for problem in problems:
        generated_testcases = generate.testcases(problem)

        def count(path):
            if type(path) is list:
                return set.union(*(count(p) for p in path))
            if callable(path):
                return path(generated_testcases)
            results: set[str | Path] = set()
            for p in glob(problem.path, path):
                if p.is_file():
                    # Exclude files containing 'TODO: Remove'.
                    try:
                        data = p.read_text()
                    except UnicodeDecodeError:
                        continue
                    if 'TODO: Remove' in data:
                        continue
                    results.add(p.stem)

                if p.is_dir():
                    ok = True
                    for f in glob(p, '*'):
                        # Exclude files containing 'TODO: Remove'.
                        if f.is_file():
                            try:
                                data = f.read_text()
                                if data.find('TODO: Remove') != -1:
                                    ok = False
                                    break
                            except UnicodeDecodeError:
                                ok = False
                                pass
                    if ok:
                        results.add(p)

            return results

        def value(x):
            if x[0] == '  time' or x[0] == 'subs':
                return x[1](problem)
            if x[0] == 'A' and (problem.interactive or problem.multipass):
                return None  # Do not show an entry for the answer validator if it is not required
            if x[0] == 'O' and problem.settings.validation == 'default':
                return None  # Do not show an entry for the output validator if it is not required
            return len(count(x[1]))

        counts = [value(s) for s in stats]
        for i in range(0, len(stats)):
            cumulative[i] += counts[i] or 0

        verified = False
        comment = ''
        if 'verified' in problem.settings:
            verified = bool(problem.settings.verified)
        if 'comment' in problem.settings:
            comment = problem.settings.comment

        if verified:
            if not comment:
                comment = 'DONE'
            comment = Fore.GREEN + comment + Style.RESET_ALL
        else:
            comment = Fore.YELLOW + comment + Style.RESET_ALL

        print(
            format_string.format(
                problem.label + ' ' + problem.name,
                *[
                    _get_stat(
                        counts[i],
                        # mypy does not support variable-length tuples very well:
                        # https://github.com/python/mypy/pull/16237#:~:text=indirect%20comparisons
                        True if len(stats[i]) <= 2 else stats[i][2],  # type: ignore[misc]
                        None if len(stats[i]) <= 3 else stats[i][3],  # type: ignore[misc]
                    )
                    for i in range(len(stats))
                ],
                comment,
            ),
            file=sys.stderr,
        )

    # print the cumulative count
    print('-' * len(header), file=sys.stderr)
    print(
        format_string.format('TOTAL', *(_get_stat(x, False) for x in cumulative), ''),
        file=sys.stderr,
    )


try:
    import pygount  # type: ignore
    import pygments  # type: ignore

    pygount.analysis._SUFFIX_TO_FALLBACK_LEXER_MAP['py3'] = pygments.lexers.PythonLexer()
    pygount.analysis._SUFFIX_TO_FALLBACK_LEXER_MAP['py2'] = pygments.lexers.PythonLexer()
    has_pygount = True
except Exception:
    has_pygount = False


def slides_stats(problems):
    if not has_pygount:
        error('stats --slides needs pygount. Install python[3]-pygount.')
        return

    stat_name_len = 10
    stat_len = 5
    columns = [p.label for p in problems] + ['sum', 'min', 'avg', 'max']

    header_string = f'{{:<{stat_name_len}}}' + f' {{:>{stat_len}}}' * len(columns)
    format_string = (
        f'{{:<{stat_name_len + len(Fore.WHITE)}}}{Style.RESET_ALL}'
        + f' {{:>{stat_len + len(Fore.WHITE)}}}{Style.RESET_ALL}' * len(columns)
    )

    def format_row(*values):
        printable = []
        for value in values:
            if isinstance(value, float):
                value = f'{value:.1f}'
            elif not isinstance(value, str):
                value = str(value)
            if not value.startswith(ansi.CSI):
                value = f'{Fore.WHITE}{value}'
            printable.append(value)
        return format_string.format(*printable)

    print(file=sys.stderr)
    header = header_string.format('', *columns)
    print(Style.BRIGHT + header + Style.RESET_ALL, file=sys.stderr)
    print('-' * len(header))

    languages: dict[str, list[str] | Literal[True]] = {
        'C(++)': ['C', 'C++'],
        'Python': ['Python 2', 'Python 3', 'CPython 2', 'CPython 3'],
        'Java': ['Java'],
        'Kotlin': ['Kotlin'],
    }

    def get_row(colum, names):
        paths = []
        if names is True:
            paths.append('submissions/accepted/*')
        else:
            assert isinstance(names, list)
            for config in program.languages().values():
                if config['name'] in names:
                    globs = config['files'].split() or []
                    paths += [f'submissions/accepted/{glob}' for glob in globs]
            paths = list(set(paths))

        lines = [colum]
        values = []
        for problem in problems:
            files = {file for path in paths for file in glob(problem.path, path)}
            if files:
                cur_lines = [
                    pygount.SourceAnalysis.from_file(file, "pygount").code_count for file in files
                ]
                best = min(cur_lines)
                values.append(best)
                lines.append(best)
            else:
                lines.append(f'{Fore.RED}-')
        lines += (
            [sum(values), min(values), statistics.mean(values), max(values)]
            if values
            else ['-'] * 4
        )
        return lines

    best = get_row('Any', True)
    print(format_row(*best), file=sys.stderr)
    for column, names in languages.items():
        values = get_row(column, names)
        for i in range(1, 1 + len(problems)):
            if values[i] == best[i]:
                values[i] = f'{Fore.CYAN}{values[i]}'
        print(format_row(*values), file=sys.stderr)

    # TODO: git rev-list --all | wc -l
    # TODO: last testcase change
    # TODO: analyze team submissions?
