from util import *


# This prints the number belonging to the count.
# This can be a red/white colored number, or Y/N
def _get_stat(count, threshold=True, upper_bound=None):
    if threshold is True:
        if count >= 1:
            return cc.white + 'Y' + cc.reset
        else:
            return cc.red + 'N' + cc.reset
    color = cc.white
    if upper_bound != None and count > upper_bound:
        color = cc.orange
    if count < threshold:
        color = cc.red
    return color + str(count) + cc.reset


def stats(problems):
    stats = [
        # Roughly in order of importance
        ('yaml', 'problem.yaml'),
        ('ini', 'domjudge-problem.ini'),
        ('tex', 'problem_statement/problem*.tex'),
        ('sol', 'problem_statement/solution.tex'),
        ('   Ival', ['input_validators/*', 'input_format_validators/*']),
        ('Oval', ['output_validators/*']),
        ('   sample', 'data/sample/*.in', 2),
        ('secret', 'data/secret/**/*.in', 15, 50),
        ('   AC', 'submissions/accepted/*', 3),
        (' WA', 'submissions/wrong_answer/*', 2),
        ('TLE', 'submissions/time_limit_exceeded/*', 1),
        ('   cpp', [
            'submissions/accepted/*.c', 'submissions/accepted/*.cpp', 'submissions/accepted/*.cc'
        ], 1),
        ('java', 'submissions/accepted/*.java', 1),
        ('py2', ['submissions/accepted/*.py', 'submissions/accepted/*.py2'], 1),
        ('py3', 'submissions/accepted/*.py3', 1),
    ]

    headers = ['problem'] + [h[0] for h in stats] + ['  comment']
    cumulative = [0] * (len(stats))

    header_string = ''
    format_string = ''
    for header in headers:
        if header in ['problem', 'comment']:
            width = len(header)
            for problem in problems:
                width = max(width, len(problem.label + ' ' + problem.name))
            header_string += '{:<' + str(width) + '}'
            format_string += '{:<' + str(width) + '}'
        else:
            width = len(header)
            header_string += ' {:>' + str(width) + '}'
            format_string += ' {:>' + str(width + len(cc.white) + len(cc.reset)) + '}'

    header = header_string.format(*headers)
    print(cc.bold + header + cc.reset)

    for problem in problems:

        def count(path):
            if type(path) is list:
                return sum(count(p) for p in path)
            cnt = 0
            for p in glob(problem.path, path):
                # Exclude files containing 'TODO: Remove'.
                if p.is_file():
                    with p.open() as file:
                        data = file.read()
                        if data.find('TODO: Remove') == -1:
                            cnt += 1
                if p.is_dir():
                    ok = True
                    for f in glob(p, '*'):
                        if f.is_file():
                            with f.open() as file:
                                data = file.read()
                                if data.find('TODO') != -1:
                                    ok = False
                                    break
                    if ok:
                        cnt += 1
            return cnt

        counts = [count(s[1]) for s in stats]
        for i in range(0, len(stats)):
            cumulative[i] = cumulative[i] + counts[i]

        verified = False
        comment = ''
        if 'verified' in problem.config:
            verified = bool(problem.config['verified'])
        if 'comment' in problem.config:
            comment = problem.config['comment']

        if verified: comment = cc.green + comment + cc.reset
        else: comment = cc.orange + comment + cc.reset

        print(
            format_string.format(
                problem.label + ' ' + problem.name, *[
                    _get_stat(counts[i], True if len(stats[i]) <= 2 else stats[i][2],
                              None if len(stats[i]) <= 3 else stats[i][3])
                    for i in range(len(stats))
                ], comment))

    # print the cumulative count
    print('-' * len(header))
    print(
        format_string.format(*(['TOTAL'] + list(map(lambda x: _get_stat(x, False), cumulative)) +
                               [''])))
