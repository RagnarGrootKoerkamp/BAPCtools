from util import *
import generate


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
        ('   sample', ['data/sample/*.in', lambda s: {x
                                                      for x in s
                                                      if x.parts[2] == 'sample'}], 2),
        ('secret', ['data/secret/**/*.in', lambda s: {x
                                                      for x in s
                                                      if x.parts[2] == 'secret'}], 15, 50),
        ('bad', 'data/bad/**/*', 0),
        ('   AC', 'submissions/accepted/*', 3),
        (' WA', 'submissions/wrong_answer/*', 2),
        ('TLE', 'submissions/time_limit_exceeded/*', 1),
        ('   cpp', [
            'submissions/accepted/*.c', 'submissions/accepted/*.cpp', 'submissions/accepted/*.cc'
        ], 1),
        ('java', 'submissions/accepted/*.java', 1),
        ('py', ['submissions/accepted/*.py[23]', 'submissions/accepted/*.py'], 1),
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
        generated_testcases = {
            problem.path / 'data' / x.parent / (x.name + '.in')
            for x in generate.generated_testcases(problem)
        }

        def count(path):
            if type(path) is list:
                return set.union(*(count(p) for p in path))
            if callable(path):
                return path(generated_testcases)
            results = set()
            for p in glob(problem.path, path):
                # Exclude files containing 'TODO: Remove'.
                if p.is_file():
                    with p.open() as file:
                        data = file.read()
                        if data.find('TODO: Remove') == -1:
                            results.add(p)
                if p.is_dir():
                    ok = True
                    for f in glob(p, '*'):
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

        counts = [len(count(s[1])) for s in stats]
        for i in range(0, len(stats)):
            cumulative[i] = cumulative[i] + counts[i]

        verified = False
        comment = ''
        if 'verified' in problem.settings:
            verified = bool(problem.settings.verified)
        if 'comment' in problem.settings:
            comment = problem.settings.comment

        if verified:
            if not comment:
                comment = 'DONE'
            comment = cc.green + comment + cc.reset
        else:
            comment = cc.orange + comment + cc.reset

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
