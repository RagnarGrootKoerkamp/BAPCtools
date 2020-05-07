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
import hashlib
import os
import sys
import tempfile

from pathlib import Path

# Local imports
import config
import constraints
import export
import generate
import latex
import run
import skel
import stats
import validate

from objects import Problem
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


def print_sorted(problems):
    prefix = config.args.contest + '/' if config.args.contest else ''
    for problem in problems:
        print(f'{problem.label:<2}: {problem.path}')


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
    genparser.add_argument('-j',
                           '--jobs',
                           type=int,
                           default=4,
                           help='The number of jobs to use. Default is 4.')

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

    # Print the corresponding temporary directory.
    tmpparser = subparsers.add_parser(
        'tmp',
        parents=[global_parser],
        help='Print the tmpdir corresponding to the current problem.')

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
        skel.new_contest(config.args.contestname)
        return

    if action in ['new_problem']:
        skel.new_problem()
        return

    if action in ['new_cfp_problem']:
        skel.new_cfp_problem(config.args.shortname)
        return

    # Get problem_paths and cd to contest
    # TODO: Migrate from plain problem paths to Problem objects.
    problems, level, contest = get_problems()
    problem_paths = [p.path for p in problems]

    if action == 'tmp':
        if level == 'problem':
            print(config.tmpdir / problems[0].name)
        else:
            print(config.tmpdir)
        return

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
        stats.stats(problems)
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
        skel.create_gitlab_jobs(contest, problem_paths)
        return

    problem_zips = []

    success = True

    for problem in problems:
        if level == 'problemset' and action == 'pdf' and not (hasattr(config.args, 'all')
                                                              and config.args.all):
            continue
        print(cc.bold, 'PROBLEM ', problem.path, cc.reset, sep='')

        # merge problem settings with arguments into one namespace
        # TODO: Fix the usages of:
        # - problem.config
        # - global config
        # - the merged settings object
        problemsettings = problem.config
        settings = argparse.Namespace(**problemsettings)
        for key in vars(config.args):
            if vars(config.args)[key] is not None:
                vars(settings)[key] = vars(config.args)[key]
        problem.settings = settings

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
            success &= generate.clean(problem)
        if action in ['generate']:
            success &= generate.generate(problem)
        if action in ['validate', 'output', 'all']:
            success &= validate.validate(problem.path, 'output', settings, input_validator_ok)
        if action in ['run', 'all']:
            success &= run.run_submissions(problem, settings)
        if action in ['test']:
            success &= run.test_submissions(problem, settings)
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
