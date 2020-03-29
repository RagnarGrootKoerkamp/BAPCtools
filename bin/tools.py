#!/usr/bin/python3
# PYTHON_ARGCOMPLETE_OK
"""Can be run on multiple levels:

    - from the root of the git repository
    - from a contest directory
    - from a problem directory
the tool will know where it is (by looking for the .git directory) and run on
everything inside it

- Ragnar Groot Koerkamp

Parts of this are copied from/based on run_program.py, written by Raymond van
Bommel.
"""

import argparse
import datetime
import hashlib
import os
import re
import shutil
import sys
import tempfile

from pathlib import Path

# Local imports
import config
from objects import *
import export
import latex
import validate
import generate
import run
import constraints
from util import *

if not is_windows():
    import argcomplete  # For automatic shell completions


# Get the list of relevant problems.
# Either use the problems.yaml, or check the existence of problem.yaml and sort
# by shortname.
def get_problems():
    def is_problem_directory(path):
        # TODO: Simplify this when problem.yaml is required.
        return (path / 'problem.yaml').is_file() or (path / 'problem_statement').is_dir()

    contest = None
    problem = None
    level = None
    if hasattr(config.args, 'contest') and config.args.contest:
        contest = config.args.contest
        os.chdir(contest)
        level = 'problemset'
    elif hasattr(config.args, 'problem') and config.args.problem:
        problem = Path(config.args.problem)
        level = 'problem'
        os.chdir(problem.parent)
    elif is_problem_directory(Path('.')):
        problem = Path().cwd()
        level = 'problem'
        os.chdir('..')
    else:
        level = 'problemset'

    problems = []
    if level == 'problem':
        # TODO: provide a label from a problems.yaml from dir above?
        # Currently, the label is parsed from the domjudge-problem.ini probid field.
        problems = [Problem(Path(problem.name))]
    else:
        level = 'problemset'
        # If problemset.yaml is available, use it.
        problemsyaml = Path('problems.yaml')
        if problemsyaml.is_file():
            # TODO: Implement label default value
            problemlist = read_yaml(problemsyaml)
            assert problemlist is not None
            labels = dict()
            nextlabel = 'A'
            problems = []
            for p in problemlist:
                label = nextlabel
                if 'label' in p: label = p['label']
                if label == '': fatal(f'Found empty label for problem {p["id"]}')
                nextlabel = label[:-1] + chr(ord(label[-1]) + 1)
                if label in labels:
                    fatal(f'label {label} found twice for problem {p["id"]} and {labels[label]}.')
                labels[label] = p['id']
                problems.append(Problem(Path(p['id']), label))
        else:
            # Otherwise, fallback to all directories with a problem.yaml and sort by
            # shortname.
            # TODO: Keep this fallback?
            label_ord = 0
            for path in glob(Path('.'), '*/'):
                if is_problem_directory(path):
                    label = chr(ord('A') + label_ord)
                    problems.append(Problem(path, label))
                    label_ord += 1

    contest = Path().cwd().name

    # We create one tmpdir per repository, assuming the repository is one level
    # higher than the contest directory.
    if config.tmpdir is None:
        h = hashlib.sha256(bytes(Path().cwd().parent)).hexdigest()[-6:]
        config.tmpdir = Path(tempfile.gettempdir()) / ('bapctools_' + h)
        config.tmpdir.mkdir(parents=True, exist_ok=True)

    return (problems, level, contest)


# This prints the number belonging to the count.
# This can be a red/white colored number, or Y/N
def get_stat(count, threshold=True, upper_bound=None):
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
                width = max(width, len(problem.label + ' ' + problem.id))
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
                problem.label + ' ' + problem.id, *[
                    get_stat(counts[i], True if len(stats[i]) <= 2 else stats[i][2],
                             None if len(stats[i]) <= 3 else stats[i][3])
                    for i in range(len(stats))
                ], comment))

    # print the cumulative count
    print('-' * len(header))
    print(
        format_string.format(*(['TOTAL'] + list(map(lambda x: get_stat(x, False), cumulative)) +
                               [''])))


def print_sorted(problems):
    prefix = config.args.contest + '/' if config.args.contest else ''
    for problem in problems:
        print(f'{problem.label:<2}: {problem.path}')


# Returns the alphanumeric version of a string:
# This reduces it to a string that follows the regex:
# [a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]
def alpha_num(string):
    s = re.sub(r'[^a-zA-Z0-9_.-]', '', string.lower().replace(' ', '').replace('-', ''))
    while s.startswith('_.-'):
        s = s[1:]
    while s.endswith('_.-'):
        s = s[:-1]
    return s


def split_submissions(s):
    # Everything containing data/, .in, or .ans goes into testcases.
    submissions = []
    testcases = []
    for p in s:
        pp = Path(p)
        if 'data/' in p or '.in' in p or '.ans' in p:
            # Strip potential .ans and .in
            if pp.suffix in ['.ans', '.in']:
                testcases.append(pp.with_suffix(''))
            else:
                testcases.append(pp)
        else:
            submissions.append(pp)
    return (submissions, testcases)


def ask_variable(name, default=None):
    if default == None:
        val = ''
        while True:
            print(f"{name}: ", end='')
            val = input()
            if val == '':
                print(f"{name} must not be empty!")
            else:
                break
        return val
    else:
        print(f"{name} [{default}]: ", end='')
        val = input()
        return default if val == '' else val


def new_contest(name):
    # Ask for all required infos.
    title = ask_variable('name', name)
    subtitle = ask_variable('subtitle', '')
    dirname = ask_variable('dirname', alpha_num(title))
    author = ask_variable('author', f'The {title} jury')
    testsession = ask_variable('testsession?', 'n (y/n)')[0] != 'n'  # boolean
    year = ask_variable('year', str(datetime.datetime.now().year))
    source = ask_variable('source', title)
    source_url = ask_variable('source url', '')
    license = ask_variable('license', 'cc by-sa')
    rights_owner = ask_variable('rights owner', 'author')

    skeldir = config.tools_root / 'skel/contest'
    copytree_and_substitute(skeldir, Path(dirname), locals(), exist_ok=False)


def new_problem():
    problemname = config.args.problemname if config.args.problemname else ask_variable(
        'problem name')
    dirname = ask_variable('dirname', alpha_num(problemname))
    author = config.args.author if config.args.author else ask_variable(
        'author', config.args.author)

    if config.args.custom_validation:
        validation = 'custom'
    elif config.args.default_validation:
        validation = 'default'
    else:
        validation = ask_variable('validation', 'default')

    # Read settings from the contest-level yaml file.
    variables = read_yaml(Path('contest.yaml'))

    for k, v in {
            'problemname': problemname,
            'dirname': dirname,
            'author': author,
            'validation': validation
    }.items():
        variables[k] = v

    for k in ['source', 'source_url', 'license', 'rights_owner']:
        if k not in variables: variables[k] = ''

    # Copy tree from the skel directory, next to the contest, if it is found.
    skeldir = config.tools_root / 'skel/problem'
    if Path('skel/problem').is_dir(): skeldir = Path('skel/problem')
    if Path('../skel/problem').is_dir(): skeldir = Path('../skel/problem')
    if config.args.skel: skeldir = Path(config.args.skel)
    print(f'Copying {skeldir} to {dirname}.')

    copytree_and_substitute(skeldir, Path(dirname), variables, exist_ok=True)


def new_cfp_problem(name):
    shutil.copytree(config.tools_root / 'skel/problem_cfp', name, symlinks=True)


def create_gitlab_jobs(contest, problems):
    def problem_source_dir(problem):
        return problem.resolve().relative_to(Path('..').resolve())

    header_yml = (config.tools_root / 'skel/gitlab-ci-header.yml').read_text()
    print(substitute(header_yml, locals()))

    contest_yml = (config.tools_root / 'skel/gitlab-ci-contest.yml').read_text()
    changes = ''
    for problem in problems:
        changes += '      - ' + str(problem_source_dir(problem)) + '/problem_statement/**/*\n'
    print(substitute(contest_yml, locals()))

    problem_yml = (config.tools_root / 'skel/gitlab-ci-problem.yml').read_text()
    for problem in problems:
        changesdir = problem_source_dir(problem)
        print('\n')
        print(substitute(problem_yml, locals()), end='')


def build_parser():
    parser = argparse.ArgumentParser(description="""
Tools for ICPC style problem sets.
Run this from one of:
    - the repository root, and supply `contest`
    - a contest directory
    - a problem directory
""",
                                     formatter_class=argparse.RawTextHelpFormatter)

    # Global options
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument(
        '-v',
        '--verbose',
        action='count',
        help='Verbose output; once for what\'s going on, twice for all intermediate output.')
    global_parser.add_argument('-c',
                               '--contest',
                               help='The contest to use, when running from repository root.')
    global_parser.add_argument('-p',
                               '--problem',
                               help='The problem to use, when running from repository root.')
    global_parser.add_argument('--no-bar',
                               action='store_true',
                               help='Do not show progress bars in non-interactive environments.')
    global_parser.add_argument('-e',
                               '--error',
                               action='store_true',
                               help='Print full output of failing commands')
    global_parser.add_argument('-E',
                               '--noerror',
                               action='store_true',
                               help='Hide output of failing commands')
    global_parser.add_argument('--cpp_flags',
                               help='Additional compiler flags used for all c++ compilations.')
    global_parser.add_argument(
        '-m',
        '--memory',
        help='The max amount of memory (in bytes) a subprocesses may use. Does not work for java.')
    global_parser.add_argument('--force_build',
                               action='store_true',
                               help='Force rebuild instead of only on changed files.')

    subparsers = parser.add_subparsers(title='actions', dest='action')
    subparsers.required = True

    # New contest
    contestparser = subparsers.add_parser('new_contest',
                                          parents=[global_parser],
                                          help='Add a new contest to the current directory.')
    contestparser.add_argument('contestname', nargs='?', help='The name of the contest')

    # New problem
    problemparser = subparsers.add_parser('new_problem',
                                          parents=[global_parser],
                                          help='Add a new problem to the current directory.')
    problemparser.add_argument('problemname', nargs='?', help='The name of the problem,')
    problemparser.add_argument('--author', help='The author of the problem,')
    problemparser.add_argument('--custom_validation',
                               action='store_true',
                               help='Use custom validation for this problem.')
    problemparser.add_argument('--default_validation',
                               action='store_true',
                               help='Use default validation for this problem.')
    problemparser.add_argument('--skel', help='Skeleton problem directory to copy from.')

    # New CfP problem
    cfpproblemparser = subparsers.add_parser('new_cfp_problem',
                                             help='Stub for minimal cfp problem.')
    cfpproblemparser.add_argument('shortname',
                                  action='store',
                                  help='The shortname/directory name of the problem.')

    # Problem statements
    pdfparser = subparsers.add_parser('pdf',
                                      parents=[global_parser],
                                      help='Build the problem statement pdf.')
    pdfparser.add_argument('-a',
                           '--all',
                           action='store_true',
                           help='Create problem statements for individual problems as well.')
    pdfparser.add_argument('--web', action='store_true', help='Create a web version of the pdf.')
    pdfparser.add_argument('--cp',
                           action='store_true',
                           help='Copy the output pdf instead of symlinking it.')
    pdfparser.add_argument('--no_timelimit', action='store_true', help='Do not print timelimits.')

    # Solution slides
    solparser = subparsers.add_parser('solutions',
                                      parents=[global_parser],
                                      help='Build the solution slides pdf.')
    solparser.add_argument('-a',
                           '--all',
                           action='store_true',
                           help='Create problem statements for individual problems as well.')
    solparser.add_argument('--cp',
                           action='store_true',
                           help='Copy the output pdf instead of symlinking it.')
    solparser.add_argument('--order',
                           action='store',
                           help='The order of the problems, e.g.: "CAB"')
    solparser.add_argument('--web', action='store_true', help='Create a web version of the pdf.')

    # Validation
    validate_parser = subparsers.add_parser('validate',
                                            parents=[global_parser],
                                            help='validate all grammar')
    validate_parser.add_argument('testcases', nargs='*', help='The testcases to run on.')
    validate_parser.add_argument('--remove', action='store_true', help='Remove failing testcsaes.')
    validate_parser.add_argument('--move_to', help='Move failing testcases to this directory.')
    input_parser = subparsers.add_parser('input',
                                         parents=[global_parser],
                                         help='validate input grammar')
    input_parser.add_argument('testcases', nargs='*', help='The testcases to run on.')
    output_parser = subparsers.add_parser('output',
                                          parents=[global_parser],
                                          help='validate output grammar')
    output_parser.add_argument('testcases', nargs='*', help='The testcases to run on.')

    subparsers.add_parser('constraints',
                          parents=[global_parser],
                          help='prints all the constraints found in problemset and validators')

    # Stats
    subparsers.add_parser('stats',
                          parents=[global_parser],
                          help='show statistics for contest/problem')

    # Generate Testcases
    genparser = subparsers.add_parser('generate',
                                      parents=[global_parser],
                                      help='Generate testcases according to .gen files.')
    genparser.add_argument('-f',
                           '--force',
                           action='store_true',
                           help='Overwrite existing input flies.')
    genparser.add_argument(
        'generators',
        nargs='*',
        help=
        'The generators to run. Everything which has one of these as a prefix will be run. Leading `data/` will be dropped. Empty to generate everything.'
    )
    genparser.add_argument('-t', '--timeout', type=int, help='Override the default timeout.')
    genparser.add_argument('--samples',
                           action='store_true',
                           help='Overwrite the samples as well, in combination with -f.')

    # Clean
    cleanparser = subparsers.add_parser('clean',
                                        parents=[global_parser],
                                        help='Delete all .in and .ans corresponding to .gen.')

    # Run
    runparser = subparsers.add_parser('run',
                                      parents=[global_parser],
                                      help='Run multiple programs against some or all input.')
    runparser.add_argument('--table',
                           action='store_true',
                           help='Print a submissions x testcases table for analysis.')
    runparser.add_argument('submissions',
                           nargs='*',
                           help='optionally supply a list of programs and testcases to run')
    runparser.add_argument('-t', '--timeout', type=int, help='Override the default timeout.')
    runparser.add_argument('--timelimit', type=int, help='Override the default timelimit.')
    runparser.add_argument('--samples', action='store_true', help='Only run on the samples.')

    # Test
    testparser = subparsers.add_parser('test',
                                       parents=[global_parser],
                                       help='Run a single program and print the output.')
    testparser.add_argument('submissions', nargs=1, help='A single submission to run')
    testparser.add_argument('testcases',
                            nargs='*',
                            help='Optionally a list of testcases to run on.')
    testparser.add_argument('--samples', action='store_true', help='Only run on the samples.')
    testparser.add_argument('-t', '--timeout', help='Override the default timeout.')

    # Sort
    subparsers.add_parser('sort',
                          parents=[global_parser],
                          help='sort the problems for a contest by name')

    # All
    allparser = subparsers.add_parser('all',
                                      parents=[global_parser],
                                      help='validate input, validate output, and run programs')
    allparser.add_argument('--cp',
                           action='store_true',
                           help='Copy the output pdf instead of symlinking it.')
    allparser.add_argument('--no_timelimit', action='store_true', help='Do not print timelimits.')

    # Build DomJudge zip
    zipparser = subparsers.add_parser('zip',
                                      parents=[global_parser],
                                      help='Create zip file that can be imported into DomJudge')
    zipparser.add_argument('--skip', action='store_true', help='Skip recreation of problem zips.')
    zipparser.add_argument('-f',
                           '--force',
                           action='store_true',
                           help='Skip validation of input and output files.')
    zipparser.add_argument('--tex',
                           action='store_true',
                           help='Store all relevant files in the problem statement directory.')
    zipparser.add_argument('--kattis',
                           action='store_true',
                           help='Make a zip more following the kattis problemarchive.com format.')
    zipparser.add_argument('--no_solutions', action='store_true', help='Do not compile solutions')

    # Build a zip with all samples.
    subparsers.add_parser('samplezip',
                          parents=[global_parser],
                          help='Create zip file of all samples.')

    # Build a directory for verification with the kattis format
    subparsers.add_parser('kattis',
                          parents=[global_parser],
                          help='Build a directory for verification with the kattis format')

    subparsers.add_parser('gitlabci',
                          parents=[global_parser],
                          help='Print a list of jobs for the given contest.')

    if not is_windows():
        argcomplete.autocomplete(parser)

    return parser


def main():
    # Build Parser
    parser = build_parser()

    # Process arguments
    config.args = parser.parse_args()
    config.verbose = config.args.verbose if hasattr(config.args,
                                                    'verbose') and config.args.verbose else 0
    action = config.args.action

    if action in ['new_contest']:
        new_contest(config.args.contestname)
        return

    if action in ['new_problem']:
        new_problem()
        return

    if action in ['new_cfp_problem']:
        new_cfp_problem(config.args.shortname)
        return

    # Get problem_paths and cd to contest
    # TODO: Migrate from plain problem paths to Problem objects.
    problems, level, contest = get_problems()
    problem_paths = [p.path for p in problems]

    if level != 'problem' and action in ['generate', 'test']:
        if action == 'generate':
            fatal('Generating testcases only works for a single problem.')
        if action == 'test':
            fatal('Testing a submission only works for a single problem.')

    if action == 'run':
        if config.args.submissions:
            if level != 'problem':
                fatal('Running a given submission only works from a problem directory.')
            (config.args.submissions, config.args.testcases) = split_submissions(
                config.args.submissions)
        else:
            config.args.testcases = []

    if action in ['stats']:
        stats(problems)
        return

    if action == 'sort':
        print_sorted(problems)
        return

    if action in ['samplezip']:
        export.build_samples_zip(problems)
        return

    if action == 'kattis':
        if level != 'new_contest':
            print('Only contest level is currently supported...')
            return
        prepare_kattis_directory()
        return

    if action == 'gitlabci':
        create_gitlab_jobs(contest, problem_paths)
        return

    problem_zips = []

    success = True

    for problem in problems:
        if level == 'problemset' and action == 'pdf' and not (hasattr(config.args, 'all')
                                                              and config.args.all):
            continue
        print(cc.bold, 'PROBLEM ', problem.path, cc.reset, sep='')

        # merge problem settings with arguments into one namespace
        problemsettings = problem.config
        settings = argparse.Namespace(**problemsettings)
        for key in vars(config.args):
            if vars(config.args)[key] is not None:
                vars(settings)[key] = vars(config.args)[key]

        if action in ['pdf', 'solutions', 'all']:
            # only build the pdf on the problem level, or on the contest level when
            # --all is passed.
            if level == 'problem' or (level == 'problemset' and hasattr(config.args, 'all')
                                      and config.args.all):
                success &= latex.build_problem_pdf(problem)

        input_validator_ok = False
        if action in ['validate', 'input', 'all']:
            input_validator_ok = validate.validate(problem.path, 'input', settings)
            success &= input_validator_ok
        if action in ['clean']:
            success &= generate.clean(problem.path)
        if action in ['generate']:
            success &= generate.generate(problem.path, settings)
        if action in ['validate', 'output', 'all']:
            success &= validate.validate(problem.path, 'output', settings, input_validator_ok)
        if action in ['run', 'all']:
            success &= run.run_submissions(problem.path, settings)
        if action in ['test']:
            success &= run.test_submissions(problem.path, settings)
        if action in ['constraints']:
            success &= constraints.check_constraints(problem.path, settings)
        if action in ['zip']:
            # For DJ: export to A.zip
            output = problem.label + '.zip'
            # For Kattis: export to shortname.zip
            if hasattr(config.args, 'kattis') and config.args.kattis:
                output = problem.path.with_suffix('.zip')

            problem_zips.append(output)
            if not config.args.skip:
                success &= latex.build_problem_pdf(problem)
                if not config.args.force:
                    success &= validate.validate(problem.path, 'input', settings)
                    success &= validate.validate(problem.path,
                                                 'output',
                                                 settings,
                                                 check_constraints=True)

                # Write to problemname.zip, where we strip all non-alphanumeric from the
                # problem directory name.
                success &= export.build_problem_zip(problem.path, output, settings)
        if action == 'kattis':
            export.prepare_kattis_problem(problem.path, settings)

        if len(problems) > 1:
            print()

    if level == 'problemset':
        print(f'{cc.bold}CONTEST {contest}{cc.reset}')

        # build pdf for the entire contest
        if action in ['pdf']:
            success &= latex.build_contest_pdf(contest, problems, web=config.args.web)

        if action in ['solutions']:
            success &= latex.build_contest_pdf(contest,
                                               problems,
                                               solutions=True,
                                               web=config.args.web)

        if action in ['zip']:
            if not config.args.kattis:
                success &= latex.build_contest_pdf(contest, problems)
                success &= latex.build_contest_pdf(contest, problems, web=True)
                if not config.args.no_solutions:
                    success &= latex.build_contest_pdf(contest, problems, solutions=True)
                    success &= latex.build_contest_pdf(contest, problems, solutions=True, web=True)

            outfile = contest + '.zip'
            if config.args.kattis: outfile = contest + '-kattis.zip'
            export.build_contest_zip(problems, problem_zips, outfile, config.args)

    if not success or config.n_error > 0 or config.n_warn > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
