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
import shutil

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
import signal

from problem import Problem
from util import *

if not is_windows():
    import argcomplete  # For automatic shell completions

# List of high level todos:
# TODO: Do more things in parallel (running testcases, building submissions)
# TODO: Get rid of old problem.path and settings objects in tools.py.
#       This mostly needs changes in the less frequently used subcommands.


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

    # We create one tmpdir per contest.
    h = hashlib.sha256(bytes(Path().cwd())).hexdigest()[-6:]
    tmpdir = Path(tempfile.gettempdir()) / ('bapctools_' + h)
    tmpdir.mkdir(parents=True, exist_ok=True)

    problems = []
    if level == 'problem':
        # TODO: provide a label from a problems.yaml from dir above?
        # Currently, the label is parsed from the domjudge-problem.ini probid field.
        problems = [Problem(Path(problem.name), tmpdir)]
    else:
        level = 'problemset'
        # If problemset.yaml is available, use it.
        problemsyaml = Path('problems.yaml')
        if problemsyaml.is_file():
            # TODO: Implement label default value
            problemlist = read_yaml(problemsyaml)
            if problemlist is None:
                fatal(f'Did not find any problem in {problemsyaml}.')
            labels = dict()
            nextlabel = 'A'
            problems = []
            for p in problemlist:
                label = nextlabel
                shortname = p['id']
                if 'label' in p: label = p['label']
                if label == '': fatal(f'Found empty label for problem {shortname}')
                nextlabel = label[:-1] + chr(ord(label[-1]) + 1)
                if label in labels:
                    fatal(
                        f'label {label} found twice for problem {shortname} and {labels[label]}.')
                labels[label] = shortname
                if Path(shortname).is_dir():
                    problems.append(Problem(Path(shortname), tmpdir, label))
                else:
                    error(
                        f'No directory found for problem {shortname} mentioned in problems.yaml.')
        else:
            # Otherwise, fallback to all directories with a problem.yaml and sort by
            # shortname.
            # TODO: Keep this fallback?
            label_ord = 0
            for path in glob(Path('.'), '*/'):
                if is_problem_directory(path):
                    label = chr(ord('A') + label_ord)
                    problems.append(Problem(path, tmpdir, label))
                    label_ord += 1
            if len(problems) == 0:
                fatal('Did not find problem.yaml. Are you running this from a problem directory?')

        if hasattr(config.args, 'order') and config.args.order is not None:
            # Sort by position of id in order
            def get_pos(id):
                if id in config.args.order: return config.args.order.index(id)
                else: return len(config.args.order) + 1

            problems.sort(key=lambda p: (get_pos(p.label), p.name))

    contest = Path().cwd().name

    return (problems, level, contest, tmpdir)


def print_sorted(problems):
    prefix = config.args.contest + '/' if config.args.contest else ''
    for problem in problems:
        print(f'{problem.label:<2}: {problem.path}')


def split_submissions_and_testcases(s):
    # Everything containing data/, .in, or .ans goes into testcases.
    submissions = []
    testcases = []
    for p in s:
        ps = str(p)
        if 'data/' in ps or '.in' in ps or '.ans' in ps:
            # Strip potential .ans and .in
            if p.suffix in ['.ans', '.in']:
                testcases.append(p.with_suffix(''))
            else:
                testcases.append(p)
        else:
            submissions.append(p)
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
        '--verbose',
        '-v',
        default=0,
        action='count',
        help='Verbose output; once for what\'s going on, twice for all intermediate output.')
    group = global_parser.add_mutually_exclusive_group()
    group.add_argument('--contest', help='The contest to use, when running from repository root.')
    group.add_argument('--problem', help='The problem to use, when running from repository root.')

    global_parser.add_argument('--no-bar',
                               action='store_true',
                               help='Do not show progress bars in non-interactive environments.')
    global_parser.add_argument(
        '--error',
        '-e',
        action='store_true',
        help='Print full error of failing commands and some succeeding commands.')
    global_parser.add_argument('--cpp_flags',
                               help='Additional compiler flags used for all c++ compilations.')
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
    problemparser.add_argument('--validation',
                               help='Use validation to use for this problem.',
                               choices=['default', 'custom', 'custom interactive'])
    problemparser.add_argument('--skel', help='Skeleton problem directory to copy from.')

    # Problem statements
    pdfparser = subparsers.add_parser('pdf',
                                      parents=[global_parser],
                                      help='Build the problem statement pdf.')
    pdfparser.add_argument('--all',
                           '-a',
                           action='store_true',
                           help='Create problem statements for individual problems as well.')
    pdfparser.add_argument('--web', action='store_true', help='Create a web version of the pdf.')
    pdfparser.add_argument('--cp',
                           action='store_true',
                           help='Copy the output pdf instead of symlinking it.')
    pdfparser.add_argument('--no-timelimit', action='store_true', help='Do not print timelimits.')

    # Solution slides
    solparser = subparsers.add_parser('solutions',
                                      parents=[global_parser],
                                      help='Build the solution slides pdf.')
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
    validate_parser.add_argument('testcases',
                                 nargs='*',
                                 type=Path,
                                 help='The testcases to run on.')
    move_or_remove_group = validate_parser.add_mutually_exclusive_group()
    move_or_remove_group.add_argument('--remove',
                                      action='store_true',
                                      help='Remove failing testcsaes.')
    move_or_remove_group.add_argument('--move-to',
                                      help='Move failing testcases to this directory.')

    # input validations
    input_parser = subparsers.add_parser('input',
                                         parents=[global_parser],
                                         help='validate input grammar')
    input_parser.add_argument('testcases', nargs='*', type=Path, help='The testcases to run on.')

    # output validation
    output_parser = subparsers.add_parser('output',
                                          parents=[global_parser],
                                          help='validate output grammar')
    output_parser.add_argument('testcases', nargs='*', type=Path, help='The testcases to run on.')

    # constraints validation
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
    genparser.add_argument('--force',
                           '-f',
                           action='store_true',
                           help='Overwrite existing input files.')
    genparser.add_argument('--all',
                           '-a',
                           action='store_true',
                           help='Regenerate all data, including up to date test cases. ')
    genparser.add_argument('--check_deterministic',
                           action='store_true',
                           help='Rerun all generators to make sure generators are deterministic.')
    genparser.add_argument('--timeout', '-t', type=int, help='Override the default timeout.')
    genparser.add_argument('--samples',
                           action='store_true',
                           help='Overwrite the samples as well, in combination with -f.')
    genparser.add_argument('--jobs',
                           '-j',
                           type=int,
                           default=4,
                           help='The number of jobs to use. Default is 4.')
    genparser.add_argument('--add-manual',
                           action='store_true',
                           help='Add manual cases to generators.yaml.')
    genparser.add_argument('--move-manual',
                           nargs='?',
                           type=Path,
                           const='generators/manual',
                           help='Move tracked inline manual cases to the given directory.',
                           metavar='TARGET_DIRECTORY=generators/manual')
    genparser.add_argument(
        'testcases',
        nargs='*',
        type=Path,
        help='The testcases to generate, given as directory, .in/.ans file, or base name.')

    # Clean
    cleanparser = subparsers.add_parser('clean',
                                        parents=[global_parser],
                                        help='Delete all .in and .ans corresponding to .gen.')
    cleanparser.add_argument('--force',
                             '-f',
                             action='store_true',
                             help='Delete all untracked files.')

    # Run
    runparser = subparsers.add_parser('run',
                                      parents=[global_parser],
                                      help='Run multiple programs against some or all input.')
    runparser.add_argument('submissions',
                           nargs='*',
                           type=Path,
                           help='optionally supply a list of programs and testcases to run')
    runparser.add_argument('--samples', action='store_true', help='Only run on the samples.')
    runparser.add_argument('--no-generate',
                           '-G',
                           action='store_true',
                           help='Do not run `generate` before running submissions.')
    runparser.add_argument('--table',
                           action='store_true',
                           help='Print a submissions x testcases table for analysis.')
    runparser.add_argument('--timeout', '-t', type=int, help='Override the default timeout.')
    runparser.add_argument('--timelimit', type=int, help='Override the default timelimit.')
    runparser.add_argument(
        '--memory',
        '-m',
        help='The max amount of memory (in bytes) a subprocesses may use. Does not work for java.')
    runparser.add_argument('--force',
                           '-f',
                           action='store_true',
                           help='Allow overwriting existing input files in generator.')

    # Test
    testparser = subparsers.add_parser('test',
                                       parents=[global_parser],
                                       help='Run a single program and print the output.')
    testparser.add_argument('submissions', nargs=1, type=Path, help='A single submission to run')
    testcasesgroup = testparser.add_mutually_exclusive_group()
    testcasesgroup.add_argument('testcases',
                                nargs='*',
                                default=[],
                                type=Path,
                                help='Optionally a list of testcases to run on.')
    testcasesgroup.add_argument('--samples', action='store_true', help='Only run on the samples.')
    testcasesgroup.add_argument(
        '--interactive',
        '-i',
        action='store_true',
        help='Run submission in interactive mode: stdin is from the command line.')
    testparser.add_argument('--timeout', '-t', type=int, help='Override the default timeout.')
    testparser.add_argument(
        '--memory',
        '-m',
        help='The max amount of memory (in bytes) a subprocesses may use. Does not work for java.')

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
    allparser.add_argument('--no-timelimit', action='store_true', help='Do not print timelimits.')
    allparser.add_argument('--clean',
                           action='store_true',
                           help='Clean up generated testcases afterwards.')

    # Build DomJudge zip
    zipparser = subparsers.add_parser('zip',
                                      parents=[global_parser],
                                      help='Create zip file that can be imported into DomJudge')
    zipparser.add_argument('--skip', action='store_true', help='Skip recreation of problem zips.')
    zipparser.add_argument('--force',
                           '-f',
                           action='store_true',
                           help='Skip validation of input and output files.')
    zipparser.add_argument('--kattis',
                           action='store_true',
                           help='Make a zip more following the kattis problemarchive.com format.')
    zipparser.add_argument('--no-solutions', action='store_true', help='Do not compile solutions')

    # Build a zip with all samples.
    subparsers.add_parser('samplezip',
                          parents=[global_parser],
                          help='Create zip file of all samples.')

    subparsers.add_parser('gitlabci',
                          parents=[global_parser],
                          help='Print a list of jobs for the given contest.')

    # Print the corresponding temporary directory.
    tmpparser = subparsers.add_parser(
        'tmp',
        parents=[global_parser],
        help='Print the tmpdir corresponding to the current problem.')
    tmpparser.add_argument(
        '--clean',
        action='store_true',
        help='Delete the temporary cache directory for the current problem/contest.')

    if not is_windows():
        argcomplete.autocomplete(parser)

    return parser


# Takes a Namespace object returned by argparse.parse_args().
def run_parsed_arguments(args):
    # Process arguments
    config.args = args
    action = config.args.action

    # Parse arguments for 'run' command.
    if action == 'run':
        if config.args.submissions:
            config.args.submissions, config.args.testcases = split_submissions_and_testcases(
                config.args.submissions)
        else:
            config.args.testcases = []

    # Skel commands.
    if action in ['new_contest']:
        skel.new_contest(config.args.contestname)
        return

    if action in ['new_problem']:
        skel.new_problem()
        return

    # Get problem_paths and cd to contest
    problems, level, contest, tmpdir = get_problems()

    # Check for incompatible actions at the problem/problemset level.
    if level != 'problem':
        if action == 'generate':
            fatal('Generating testcases only works for a single problem.')
        if action == 'test':
            fatal('Testing a submission only works for a single problem.')

    if level != 'problemset':
        if action == 'solutions':
            fatal('Generating solution slides only works for a contest.')

    # 'submissions' and 'testcases' are only allowed at the problem level, and only when --problem is not specified.
    if level != 'problem' or config.args.problem is not None:
        if hasattr(config.args, 'submissions') and config.args.submissions:
            fatal(
                'Passing in a list of submissions only works when running from a problem directory.'
            )
        if hasattr(config.args, 'testcases') and config.args.testcases:
            fatal(
                'Passing in a list of testcases only works when running from a problem directory.')

    if hasattr(config.args, 'testcases') and config.args.testcases and hasattr(
            config.args, 'samples') and config.args.samples:
        fatal('--samples can not go together with an explicit list of testcases.')

    if hasattr(config.args, 'move_manual') and config.args.move_manual:
        # Path *must* be inside generators/.
        try:
            config.args.move_manual = (problems[0].path / config.args.move_manual).resolve()
            config.args.move_manual.relative_to(problems[0].path.resolve() / 'generators')
        except Exception as e:
            fatal('Directory given to move_manual must be inside generators/.')
        config.args.add_manual = True

    # Handle one-off subcommands.
    if action == 'tmp':
        if level == 'problem':
            level_tmpdir = tmpdir / problems[0].name
        else:
            level_tmpdir = tmpdir

        if config.args.clean:
            log(f'Deleting {tmpdir}!')
            if level_tmpdir.is_dir():
                shutil.rmtree(level_tmpdir)
            if level_tmpdir.is_file():
                level_tmpdir.unlink()
        else:
            print(level_tmpdir)

        return

    if action in ['stats']:
        stats.stats(problems)
        return

    if action == 'sort':
        print_sorted(problems)
        return

    if action in ['samplezip']:
        export.build_samples_zip(problems)
        return

    if action == 'gitlabci':
        skel.create_gitlab_jobs(contest, problems)
        return

    problem_zips = []

    success = True

    for problem in problems:
        if level == 'problemset' and action == 'pdf' and not (hasattr(config.args, 'all')
                                                              and config.args.all):
            continue
        print(cc.bold, 'PROBLEM ', problem.name, cc.reset, sep='')

        # TODO: Remove usages of settings.
        settings = problem.settings

        if action in ['generate']:
            success &= generate.generate(problem)
        if action in ['all', 'constraints'] or (action in ['run'] and not config.args.no_generate):
            # Call `generate` with modified arguments.
            old_args = argparse.Namespace(**vars(config.args))
            config.args.check_deterministic = action in ['all', 'constraints']
            config.args.jobs = 4
            config.args.add_manual = False
            config.args.move_manual = False
            config.args.verbose = 0
            if not hasattr(config.args, 'testcases'):
                config.args.testcases = None
            if not hasattr(config.args, 'force'):
                config.args.force = False
            success &= generate.generate(problem)
            config.args = old_args
        if action in ['pdf', 'all']:
            # only build the pdf on the problem level, or on the contest level when
            # --all is passed.
            if level == 'problem' or (level == 'problemset' and hasattr(config.args, 'all')
                                      and config.args.all):
                success &= latex.build_problem_pdf(problem)
        if action in ['validate', 'input', 'all']:
            success &= problem.validate_format('input_format')
        if action in ['validate', 'output', 'all']:
            success &= problem.validate_format('output_format')
        if action in ['run', 'all']:
            success &= problem.run_submissions()
        if action in ['test']:
            config.args.no_bar = True
            success &= problem.test_submissions()
        if action in ['constraints']:
            success &= constraints.check_constraints(problem, settings)
        if action in ['zip']:
            # For DOMjudge: export to A.zip
            output = problem.label + '.zip'
            # For Kattis: export to shortname.zip
            if hasattr(config.args, 'kattis') and config.args.kattis:
                output = problem.path.with_suffix('.zip')

            problem_zips.append(output)
            if not config.args.skip:
                success &= latex.build_problem_pdf(problem)
                if not config.args.force:
                    success &= problem.validate_format('input_format', check_constraints=True)
                    success &= problem.validate_format('output_format', check_constraints=True)

                # Write to problemname.zip, where we strip all non-alphanumeric from the
                # problem directory name.
                success &= export.build_problem_zip(problem.path, output, settings)
        if action in ['clean'] or (action in ['all'] and config.args.clean):
            if not hasattr(config.args, 'force'):
                config.args.force = False
            success &= generate.clean(problem)

        if len(problems) > 1:
            print()

    if level == 'problemset':
        print(f'{cc.bold}CONTEST {contest}{cc.reset}')

        # build pdf for the entire contest
        if action in ['pdf']:
            success &= latex.build_contest_pdf(contest, problems, tmpdir, web=config.args.web)

        if action in ['solutions']:
            success &= latex.build_contest_pdf(contest,
                                               problems,
                                               tmpdir,
                                               solutions=True,
                                               web=config.args.web)

        if action in ['zip']:
            if not config.args.kattis:
                success &= latex.build_contest_pdf(contest, problems, tmpdir)
                success &= latex.build_contest_pdf(contest, problems, tmpdir, web=True)
                if not config.args.no_solutions:
                    success &= latex.build_contest_pdf(contest, problems, tmpdir, solutions=True)
                    success &= latex.build_contest_pdf(contest,
                                                       problems,
                                                       tmpdir,
                                                       solutions=True,
                                                       web=True)

            outfile = contest + '.zip'
            if config.args.kattis: outfile = contest + '-kattis.zip'
            export.build_contest_zip(problems, problem_zips, outfile, config.args)

    if not success or config.n_error > 0 or config.n_warn > 0:
        sys.exit(1)


# Takes command line arguments
def main():
    parser = build_parser()
    run_parsed_arguments(parser.parse_args())


if __name__ == '__main__':

    def interrupt_handler(sig, frame):
        fatal('Running interrupted')

    signal.signal(signal.SIGINT, interrupt_handler)
    main()


def test(args):
    config.RUNNING_TEST = True

    # Make sure to cd back to the original directory before returning.
    # Needed to stay in the same directory in tests.
    original_directory = Path().cwd()
    config.n_warn = 0
    config.n_error = 0
    try:
        parser = build_parser()
        run_parsed_arguments(parser.parse_args(args))
    finally:
        os.chdir(original_directory)
