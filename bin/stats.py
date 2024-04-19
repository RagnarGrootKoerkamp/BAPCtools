from util import *
from colorama import Fore, Style
import generate
import sys
import numbers


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
    if upper_bound != None and count > upper_bound:
        color = Fore.YELLOW
    if count < threshold:
        color = Fore.RED
    return color + str(count) + Style.RESET_ALL


def stats(problems):
    stats = [
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
            15,
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
        (
            '  cpp',
            ['submissions/accepted/*.c', 'submissions/accepted/*.cpp', 'submissions/accepted/*.cc'],
            1,
        ),
        ('py', ['submissions/accepted/*.py3', 'submissions/accepted/*.py'], 1),
        ('java', 'submissions/accepted/*.java', 1),
        ('kt', 'submissions/accepted/*.kt', 1),
    ]

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
            results = set()
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
                        True if len(stats[i]) <= 2 else stats[i][2],
                        None if len(stats[i]) <= 3 else stats[i][3],
                    )
                    for i in range(len(stats))
                ],
                comment
            ),
            file=sys.stderr,
        )

    # print the cumulative count
    print('-' * len(header), file=sys.stderr)
    print(
        format_string.format('TOTAL', *(_get_stat(x, False) for x in cumulative), ''),
        file=sys.stderr,
    )
