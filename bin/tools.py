#!/usr/bin/env python3
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
import colorama
import json

from pathlib import Path

# Local imports
import config
import constraints
import export
import generate
import fuzz
import latex
import run
import skel
import slack
import solve_stats
import stats
import validate
import signal

from problem import Problem
import contest
from contest import *
from util import *

if not is_windows():
    import argcomplete  # For automatic shell completions

# Initialize colorama for printing coloured output. On Windows, this captures
# stdout and replaces ANSI colour codes by calls to change the terminal colour.
#
# This initialization is disabled on GITLAB CI, since Colorama detects that
# the terminal is not a TTY and will strip all colour codes. Instead, we just
# disable this call since capturing of stdout/stderr isn't needed on Linux
# anyway.
# See:
# - https://github.com/conan-io/conan/issues/4718#issuecomment-473102953
# - https://docs.gitlab.com/runner/faq/#how-can-i-get-colored-output-on-the-web-terminal
if not os.getenv('GITLAB_CI', False):
    colorama.init()

# List of high level todos:
# TODO: Do more things in parallel (running testcases, building submissions)
# TODO: Get rid of old problem.path and settings objects in tools.py.
#       This mostly needs changes in the less frequently used subcommands.

# Make sure f-strings are supported.
f'f-strings are not supported by your python version. You need at least python 3.6.'


# Get the list of relevant problems.
# Either use the problems.yaml, or check the existence of problem.yaml and sort
# by shortname.
def get_problems():
    def is_problem_directory(path):
        return (path / 'problem.yaml').is_file()

    contest = None
    problem = None
    level = None
    if config.args.contest:
        contest = config.args.contest.resolve()
        os.chdir(contest)
        level = 'problemset'
    if config.args.problem:
        problem = config.args.problem.resolve()
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

    def parse_problems_yaml(problemlist):
        if problemlist is None:
            fatal(f'Did not find any problem in {problemsyaml}.')
        problemlist = problemlist
        if problemlist is None:
            problemlist = []
        if not isinstance(problemlist, list):
            fatal(f'problems.yaml must contain a problems: list.')

        labels = dict()
        problems = []
        for p in problemlist:
            shortname = p['id']
            if 'label' not in p:
                fatal(f'Found no label for problem {shortname} in problems.yaml.')
            label = p['label']
            if label == '':
                fatal(f'Found empty label for problem {shortname} in problems.yaml.')
            if label in labels:
                fatal(
                    f'problems.yaml: label {label} found twice for problem {shortname} and {labels[label]}.'
                )
            labels[label] = shortname
            if Path(shortname).is_dir():
                problems.append((shortname, label))
            else:
                error(f'No directory found for problem {shortname} mentioned in problems.yaml.')
        return problems

    def fallback_problems():
        problem_paths = list(filter(is_problem_directory, glob(Path('.'), '*/')))
        label = chr(ord('Z') - len(problem_paths) + 1) if contest_yaml().get('testsession') else 'A'
        problems = []
        for i, path in enumerate(problem_paths):
            problems.append((path, label))
            label = inc_label(label)
        return problems

    problems = []
    if level == 'problem':
        # If the problem is mentioned in problems.yaml, use that ID.
        problemsyaml = problems_yaml()
        if problemsyaml:
            problem_labels = parse_problems_yaml(problemsyaml)
            for shortname, label in problem_labels:
                if shortname == problem.name:
                    problems = [Problem(Path(problem.name), tmpdir, label)]
                    break

        if len(problems) == 0:
            label = None
            for p, l in fallback_problems():
                if p.name == problem.name:
                    label = l
            problems = [Problem(Path(problem.name), tmpdir, label)]
    else:
        level = 'problemset'
        # If problems.yaml is available, use it.
        problemsyaml = problems_yaml()
        if problemsyaml:
            problems = []
            problem_labels = parse_problems_yaml(problemsyaml)
            for shortname, label in problem_labels:
                problems.append(Problem(Path(shortname), tmpdir, label))
        else:
            # Otherwise, fallback to all directories with a problem.yaml and sort by shortname.
            problems = []
            for path, label in fallback_problems():
                problems.append(Problem(path, tmpdir, label))
            if len(problems) == 0:
                fatal('Did not find problem.yaml. Are you running this from a problem directory?')

        if config.args.order:
            # Sort by position of id in order
            def get_pos(id):
                if id in config.args.order:
                    return config.args.order.index(id)
                else:
                    return len(config.args.order) + 1

            problems.sort(key=lambda p: (get_pos(p.label), p.label))

        if config.args.order_from_ccs:
            # Sort by increasing difficulty, extracted from the CCS api.
            # Get active contest.

            cid = get_contest_id()
            solves = dict()

            # Read set of problems
            response = call_api('GET', f'/contests/{cid}/problems?public=true')
            response.raise_for_status()
            contest_problems = json.loads(response.text)
            assert isinstance(problems, list)
            for problem in contest_problems:
                solves[problem['id']] = 0

            response = call_api('GET', f'/contests/{cid}/scoreboard?public=true')
            response.raise_for_status()
            scoreboard = json.loads(response.text)

            for team in scoreboard['rows']:
                for problem in team['problems']:
                    if problem['solved']:
                        solves[problem['problem_id']] += 1

            # Convert away from defaultdict, so any non matching keys below raise an error.
            solves = dict(solves)
            verbose('solves: ' + str(solves))

            # Sort the problems
            # Use negative solves instead of reversed, to preserver stable order.
            problems.sort(key=lambda p: (-solves[p.name], p.label))
            order = ', '.join(map(lambda p: p.label, problems))
            verbose('order: ' + order)

    contest = Path().cwd().name

    # Filter problems by submissions/testcases, if given.
    if level == 'problemset' and (config.args.submissions or config.args.testcases):
        submissions = config.args.submissions or []
        testcases = config.args.testcases or []

        def keep_problem(problem):
            for s in submissions:
                x = resolve_path_argument(problem, s, 'submissions')
                if x:
                    if is_relative_to(problem.path, x):
                        return True
            for t in testcases:
                x = resolve_path_argument(problem, t, 'data', suffixes=['.in'])
                if x:
                    if is_relative_to(problem.path, x):
                        return True
            return False

        problems = [p for p in problems if keep_problem(p)]

    config.level = level
    return (problems, level, contest, tmpdir)


# NOTE: This is one of the few places that prints to stdout instead of stderr.
def print_sorted(problems):
    for problem in problems:
        print(f'{problem.label:<2}: {problem.path}')


def split_submissions_and_testcases(s):
    # Everything containing data/, .in, or .ans goes into testcases.
    submissions = []
    testcases = []
    for p in s:
        ps = str(p)
        if 'data' in ps or 'sample' in ps or 'secret' in ps or '.in' in ps or '.ans' in ps:
            # Strip potential .ans and .in
            if p.suffix in ['.ans', '.in']:
                testcases.append(p.with_suffix(''))
            else:
                testcases.append(p)
        else:
            submissions.append(p)
    return (submissions, testcases)


# We set argument_default=SUPPRESS in all parsers,
# to make sure no default values (like `False` or `0`) end up in the parsed arguments object.
# If we would not do this, it would not be possible to check which keys are explicitly set from the command line.
# This check is necessary when loading the personal config file in `read_personal_config`.
class SuppressingParser(argparse.ArgumentParser):
    def __init__(self, **kwargs):
        super(SuppressingParser, self).__init__(**kwargs, argument_default=argparse.SUPPRESS)


def build_parser():
    parser = SuppressingParser(
        description="""
Tools for ICPC style problem sets.
Run this from one of:
    - the repository root, and supply `contest`
    - a contest directory
    - a problem directory
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Global options
    global_parser = SuppressingParser(add_help=False)
    global_parser.add_argument(
        '--verbose',
        '-v',
        action='count',
        help='Verbose output; once for what\'s going on, twice for all intermediate output.',
    )
    group = global_parser.add_mutually_exclusive_group()
    group.add_argument('--contest', type=Path, help='Path to the contest to use.')
    group.add_argument(
        '--problem',
        type=Path,
        help='Path to the problem to use. Can be relative to contest if given.',
    )

    global_parser.add_argument(
        '--no-bar',
        action='store_true',
        help='Do not show progress bars in non-interactive environments.',
    )
    global_parser.add_argument(
        '--error',
        '-e',
        action='store_true',
        help='Print full error of failing commands and some succeeding commands.',
    )
    global_parser.add_argument(
        '--force-build', action='store_true', help='Force rebuild instead of only on changed files.'
    )
    global_parser.add_argument(
        '--jobs',
        '-j',
        type=int,
        help='The number of jobs to use. Default: cpu_count()/2.',
    )
    global_parser.add_argument(
        '--memory',
        '-m',
        help='The maximum amount of memory in MB a subprocess may use. Does not work for Java. Default: 2048.',
    )
    global_parser.add_argument(
        '--api',
        help='CCS API endpoint to use, e.g. https://www.domjudge.org/demoweb. Defaults to the value in contest.yaml.',
    )
    global_parser.add_argument('--username', '-u', help='The username to login to the CCS.')
    global_parser.add_argument('--password', '-p', help='The password to login to the CCS.')
    global_parser.add_argument(
        '--cp', action='store_true', help='Copy the output pdf instead of symlinking it.'
    )
    global_parser.add_argument(
        '--language', dest='languages', action='append', help='Set language.'
    )

    subparsers = parser.add_subparsers(
        title='actions', dest='action', parser_class=SuppressingParser
    )
    subparsers.required = True

    # New contest
    contestparser = subparsers.add_parser(
        'new_contest', parents=[global_parser], help='Add a new contest to the current directory.'
    )
    contestparser.add_argument('contestname', nargs='?', help='The name of the contest')

    # New problem
    problemparser = subparsers.add_parser(
        'new_problem', parents=[global_parser], help='Add a new problem to the current directory.'
    )
    problemparser.add_argument('problemname', nargs='?', help='The name of the problem,')
    problemparser.add_argument('--author', help='The author of the problem,')
    problemparser.add_argument(
        '--validation',
        help='Use validation to use for this problem.',
        choices=[
            'default',
            'custom',
            'custom interactive',
            'custom multi-pass',
            'custom interactive multi-pass',
        ],
    )
    problemparser.add_argument('--skel', help='Skeleton problem directory to copy from.')

    # Copy directory from skel.
    skelparser = subparsers.add_parser(
        'skel',
        parents=[global_parser],
        help='Copy the given directories from skel to the current problem directory.',
    )
    skelparser.add_argument(
        'directory',
        nargs='+',
        help='Directories to copy from skel/problem/, relative to the problem directory.',
    )
    skelparser.add_argument('--skel', help='Skeleton problem directory to copy from.')

    # Rename problem
    renameproblemparser = subparsers.add_parser(
        'rename_problem', parents=[global_parser], help='Rename a problem, including its directory.'
    )
    renameproblemparser.add_argument('problemname', nargs='?', help='The new name of the problem,')

    # Problem statements
    pdfparser = subparsers.add_parser(
        'pdf', parents=[global_parser], help='Build the problem statement pdf.'
    )
    pdfparser.add_argument(
        '--all',
        '-a',
        action='store_true',
        help='Create problem statements for individual problems as well.',
    )
    pdfparser.add_argument('--no-timelimit', action='store_true', help='Do not print timelimits.')
    pdfparser.add_argument(
        '--watch',
        '-w',
        action='store_true',
        help='Continuously compile the pdf whenever a `problem_statement.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files. Further Note that this implies `--cp`.',
    )
    pdfparser.add_argument(
        '--open',
        '-o',
        nargs='?',
        const=True,
        type=Path,
        help='Open the continuously compiled pdf (with a specified program).',
    )
    pdfparser.add_argument('--web', action='store_true', help='Create a web version of the pdf.')
    pdfparser.add_argument('-1', action='store_true', help='Only run the LaTeX compiler once.')

    # Solution slides
    solparser = subparsers.add_parser(
        'solutions', parents=[global_parser], help='Build the solution slides pdf.'
    )
    orderparser = solparser.add_mutually_exclusive_group()
    orderparser.add_argument(
        '--order', action='store', help='The order of the problems, e.g.: "CAB"'
    )
    orderparser.add_argument(
        '--order-from-ccs',
        action='store_true',
        help='Order the problems by increasing difficulty, extracted from the CCS.',
    )
    solparser.add_argument(
        '--contest-id',
        action='store',
        help='Contest ID to use when reading from the API. Only useful with --order-from-ccs. Defaults to value of contest_id in contest.yaml.',
    )
    solparser.add_argument(
        '--watch',
        '-w',
        action='store_true',
        help='Continuously compile the pdf whenever a `solution.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files. Further Note that this implies `--cp`.',
    )
    solparser.add_argument(
        '--open',
        '-o',
        nargs='?',
        const=True,
        type=Path,
        help='Open the continuously compiled pdf  (with a specified program).',
    )
    solparser.add_argument('--web', action='store_true', help='Create a web version of the pdf.')
    solparser.add_argument('-1', action='store_true', help='Only run the LaTeX compiler once.')

    # Validation
    validate_parser = subparsers.add_parser(
        'validate', parents=[global_parser], help='validate all grammar'
    )
    validate_parser.add_argument('testcases', nargs='*', type=Path, help='The testcases to run on.')
    input_answer_group = validate_parser.add_mutually_exclusive_group()
    input_answer_group.add_argument(
        '--input', '-i', action='store_true', help='Only validate input.'
    )
    input_answer_group.add_argument('--answer', action='store_true', help='Only validate answer.')
    input_answer_group.add_argument(
        '--invalid', action='store_true', help='Only check invalid files for validity.'
    )

    move_or_remove_group = validate_parser.add_mutually_exclusive_group()
    move_or_remove_group.add_argument(
        '--remove', action='store_true', help='Remove failing testcases.'
    )
    move_or_remove_group.add_argument('--move-to', help='Move failing testcases to this directory.')

    validate_parser.add_argument(
        '--no-testcase-sanity-checks',
        action='store_true',
        help='Skip sanity checks on testcases.',
    )
    validate_parser.add_argument(
        '--timeout', '-t', type=int, help='Override the default timeout. Default: 30.'
    )

    # constraints validation
    constraintsparser = subparsers.add_parser(
        'constraints',
        parents=[global_parser],
        help='prints all the constraints found in problemset and validators',
    )

    constraintsparser.add_argument(
        '--no-generate', '-G', action='store_true', help='Do not run `generate`.'
    )

    # Stats
    subparsers.add_parser(
        'stats', parents=[global_parser], help='show statistics for contest/problem'
    )

    # Generate Testcases
    genparser = subparsers.add_parser(
        'generate', parents=[global_parser], help='Generate testcases according to .gen files.'
    )
    genparser.add_argument(
        '--check-deterministic',
        action='store_true',
        help='Rerun all generators to make sure generators are deterministic.',
    )
    genparser.add_argument(
        '--timeout', '-t', type=int, help='Override the default timeout. Default: 30.'
    )

    genparser_group = genparser.add_mutually_exclusive_group()
    genparser_group.add_argument(
        '--add',
        nargs='*',
        type=Path,
        help='Add case(s) to generators.yaml.',
        metavar='TARGET_DIRECTORY=generators/manual',
    )
    genparser_group.add_argument(
        '--clean', '-C', action='store_true', help='Delete all cached files.'
    )

    genparser.add_argument(
        '--interaction',
        '-i',
        action='store_true',
        help='Use the solution to generate .interaction files.',
    )
    genparser.add_argument(
        'testcases',
        nargs='*',
        type=Path,
        help='The testcases to generate, given as directory, .in/.ans file, or base name.',
    )
    genparser.add_argument(
        '--default-solution',
        '-s',
        type=Path,
        help='The default solution to use for generating .ans files. Not compatible with generator.yaml.',
    )
    genparser.add_argument(
        '--no-validators',
        action='store_true',
        help='Ignore results of input and answer validation. Validators are still run.',
    )
    genparser.add_argument(
        '--no-solution',
        action='store_true',
        help='Skip generating .ans/.interaction files with the solution.',
    )
    genparser.add_argument(
        '--no-visualizer',
        action='store_true',
        help='Skip generating graphics with the visualizer.',
    )
    genparser.add_argument(
        '--no-testcase-sanity-checks',
        action='store_true',
        help='Skip sanity checks on testcases.',
    )

    # Fuzzer
    fuzzparser = subparsers.add_parser(
        'fuzz',
        parents=[global_parser],
        help='Generate random testcases and search for inconsistencies in AC submissions.',
    )
    fuzzparser.add_argument('--time', type=int, help=f'Number of seconds to run for. Default: 600')
    fuzzparser.add_argument('--timelimit', '-t', type=int, help=f'Time limit for submissions.')
    fuzzparser.add_argument(
        'submissions',
        nargs='*',
        type=Path,
        help='The generator.yaml rules to use, given as directory, .in/.ans file, or base name, and submissions to run.',
    )
    fuzzparser.add_argument(
        '--timeout', type=int, help='Override the default timeout. Default: 30.'
    )

    # Run
    runparser = subparsers.add_parser(
        'run', parents=[global_parser], help='Run multiple programs against some or all input.'
    )
    runparser.add_argument(
        'submissions',
        nargs='*',
        type=Path,
        help='optionally supply a list of programs and testcases to run',
    )
    runparser.add_argument('--samples', action='store_true', help='Only run on the samples.')
    runparser.add_argument(
        '--no-generate',
        '-G',
        action='store_true',
        help='Do not run `generate` before running submissions.',
    )
    runparser.add_argument(
        '--all',
        '-a',
        action='count',
        default=0,
        help='Run all testcases. Use twice to continue even after timeouts.',
    )
    runparser.add_argument(
        '--default-solution',
        '-s',
        type=Path,
        help='The default solution to use for generating .ans files. Not compatible with generators.yaml.',
    )
    runparser.add_argument(
        '--table', action='store_true', help='Print a submissions x testcases table for analysis.'
    )
    runparser.add_argument(
        '--overview', '-o', action='store_true', help='Print a live overview for the judgings.'
    )
    runparser.add_argument('--tree', action='store_true', help='Show a tree of verdicts.')

    runparser.add_argument('--depth', type=int, help='Depth of verdict tree.')
    runparser.add_argument(
        '--timeout',
        type=int,
        help='Override the default timeout. Default: 1.5 * timelimit + 1.',
    )
    runparser.add_argument('--timelimit', '-t', type=int, help='Override the default timelimit.')
    runparser.add_argument(
        '--no-testcase-sanity-checks',
        action='store_true',
        help='Skip sanity checks on testcases.',
    )
    runparser.add_argument(
        '--sanitizer',
        action='store_true',
        help='Run submissions with additional sanitizer flags (currently only C++). Note that this sets --memory unlimited.',
    )

    # Test
    testparser = subparsers.add_parser(
        'test', parents=[global_parser], help='Run a single program and print the output.'
    )
    testparser.add_argument('submissions', nargs=1, type=Path, help='A single submission to run')
    testcasesgroup = testparser.add_mutually_exclusive_group()
    testcasesgroup.add_argument(
        'testcases',
        nargs='*',
        default=[],
        type=Path,
        help='Optionally a list of testcases to run on.',
    )
    testcasesgroup.add_argument('--samples', action='store_true', help='Only run on the samples.')
    testcasesgroup.add_argument(
        '--interactive',
        '-i',
        action='store_true',
        help='Run submission in interactive mode: stdin is from the command line.',
    )
    testparser.add_argument(
        '--timeout',
        type=int,
        help='Override the default timeout. Default: 1.5 * timelimit + 1.',
    )

    # Sort
    subparsers.add_parser(
        'sort', parents=[global_parser], help='sort the problems for a contest by name'
    )

    # All
    allparser = subparsers.add_parser(
        'all', parents=[global_parser], help='validate input, validate answers, and run programs'
    )
    allparser.add_argument('--no-timelimit', action='store_true', help='Do not print timelimits.')
    allparser.add_argument(
        '--no-testcase-sanity-checks',
        action='store_true',
        help='Skip sanity checks on testcases.',
    )
    allparser.add_argument(
        '--check-deterministic',
        action='store_true',
        help='Rerun all generators to make sure generators are deterministic.',
    )
    allparser.add_argument(
        '--timeout', '-t', type=int, help='Override the default timeout. Default: 30.'
    )
    allparser.add_argument(
        '--overview', '-o', action='store_true', help='Print a live overview for the judgings.'
    )

    # Build DOMjudge zip
    zipparser = subparsers.add_parser(
        'zip', parents=[global_parser], help='Create zip file that can be imported into DOMjudge'
    )
    zipparser.add_argument('--skip', action='store_true', help='Skip recreation of problem zips.')
    zipparser.add_argument(
        '--force', '-f', action='store_true', help='Skip validation of input and answers.'
    )
    zipparser.add_argument(
        '--kattis',
        action='store_true',
        help='Make a zip more following the kattis problemarchive.com format.',
    )
    zipparser.add_argument('--no-solutions', action='store_true', help='Do not compile solutions')

    # Build a zip with all samples.
    subparsers.add_parser(
        'samplezip', parents=[global_parser], help='Create zip file of all samples.'
    )

    subparsers.add_parser(
        'gitlabci', parents=[global_parser], help='Print a list of jobs for the given contest.'
    )

    exportparser = subparsers.add_parser(
        'export', parents=[global_parser], help='Export the problem or contest to DOMjudge.'
    )
    exportparser.add_argument(
        '--contest-id',
        action='store',
        help='Contest ID to use when writing to the API. Defaults to value of contest_id in contest.yaml.',
    )

    updateproblemsyamlparser = subparsers.add_parser(
        'update_problems_yaml',
        parents=[global_parser],
        help='Update the problems.yaml with current names and timelimits.',
    )
    updateproblemsyamlparser.add_argument(
        '--colors',
        help='Set the colors of the problems. Comma-separated list of hex-codes.',
    )

    # Print the corresponding temporary directory.
    tmpparser = subparsers.add_parser(
        'tmp',
        parents=[global_parser],
        help='Print the tmpdir corresponding to the current problem.',
    )
    tmpparser.add_argument(
        '--clean',
        action='store_true',
        help='Delete the temporary cache directory for the current problem/contest.',
    )

    solvestatsparser = subparsers.add_parser(
        'solve_stats',
        parents=[global_parser],
        help='Make solve stats plots using Matplotlib. All teams on the public scoreboard are included (including spectator/company teams).',
    )
    solvestatsparser.add_argument(
        '--contest-id',
        action='store',
        help='Contest ID to use when reading from the API. Defaults to value of contest_id in contest.yaml.',
    )
    solvestatsparser.add_argument(
        '--post-freeze',
        action='store_true',
        help='When given, the solve stats will include submissions from after the scoreboard freeze.',
    )

    create_slack_channel_parser = subparsers.add_parser(
        'create_slack_channels',
        parents=[global_parser],
        help='Create a slack channel for each problem',
    )
    create_slack_channel_parser.add_argument('--token', help='A user token is of the form xoxp-...')

    join_slack_channel_parser = subparsers.add_parser(
        'join_slack_channels',
        parents=[global_parser],
        help='Join a slack channel for each problem',
    )
    join_slack_channel_parser.add_argument('--token', help='A bot/user token is of the form xox...')
    join_slack_channel_parser.add_argument('username', help='Slack username')

    if not is_windows():
        argcomplete.autocomplete(parser)

    return parser


# Takes a Namespace object returned by argparse.parse_args().
def run_parsed_arguments(args):
    # Process arguments
    config.args = args
    config.set_default_args()

    action = config.args.action

    # Split submissions and testcases when needed.
    if action in ['run', 'fuzz']:
        if config.args.submissions:
            config.args.submissions, config.args.testcases = split_submissions_and_testcases(
                config.args.submissions
            )
        else:
            config.args.testcases = []

    # Skel commands.
    if action == 'new_contest':
        skel.new_contest()
        return

    if action == 'new_problem':
        skel.new_problem()
        return

    # Get problem_paths and cd to contest
    problems, level, contest, tmpdir = get_problems()

    # Check for incompatible actions at the problem/problemset level.
    if level != 'problem':
        if action == 'test':
            fatal('Testing a submission only works for a single problem.')
        if action == 'skel':
            fatal('Copying skel directories only works for a single problem.')

    if action != 'generate' and config.args.testcases and config.args.samples:
        fatal('--samples can not go together with an explicit list of testcases.')

    if config.args.add is not None:
        # default to 'generators/manual'
        if len(config.args.add) == 0:
            config.args.add = [Path('generators/manual')]

        # Paths *must* be inside generators/.
        checked_paths = []
        for path in config.args.add:
            if path.parts[0] != 'generators':
                warn(f'Path {path} does not math "generators/*". Skipping.')
            else:
                checked_paths.append(path)
        config.args.add = checked_paths

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

    if action == 'stats':
        stats.stats(problems)
        return

    if action == 'sort':
        print_sorted(problems)
        return

    if action == 'samplezip':
        sampleout = Path('samples.zip')
        if level == 'problem':
            sampleout = problems[0].path / sampleout
        statement_language = export.force_single_language(problems)
        export.build_samples_zip(problems, sampleout, statement_language)
        return

    if action == 'rename_problem':
        if level == 'problemset':
            fatal('rename_problem only works for a problem')
        skel.rename_problem(problems[0])
        return

    if action == 'gitlabci':
        skel.create_gitlab_jobs(contest, problems)
        return

    if action == 'skel':
        skel.copy_skel_dir(problems)
        return

    if action == 'solve_stats':
        if level == 'problem':
            fatal('solve_stats only works for a contest')
        solve_stats.generate_solve_stats(config.args.post_freeze)
        return

    if action == 'create_slack_channels':
        slack.create_slack_channels(problems)
        return

    if action == 'join_slack_channels':
        slack.join_slack_channels(problems, config.args.username)
        return

    problem_zips = []

    success = True

    for problem in problems:
        if (
            level == 'problemset'
            and action in ['pdf', 'export', 'update_problems_yaml']
            and not config.args.all
        ):
            continue
        print(Style.BRIGHT, 'PROBLEM ', problem.name, Style.RESET_ALL, sep='', file=sys.stderr)

        if action in ['generate']:
            success &= generate.generate(problem)
        if action in ['all', 'constraints', 'run'] and not config.args.no_generate:
            # Call `generate` with modified arguments.
            old_args = argparse.Namespace(**vars(config.args))
            config.args.jobs = os.cpu_count() // 2
            config.args.add = None
            config.args.verbose = 0
            config.args.no_visualizer = True
            success &= generate.generate(problem)
            config.args = old_args
        if action in ['fuzz']:
            success &= fuzz.Fuzz(problem).run()
        if action in ['pdf', 'all']:
            # only build the pdf on the problem level, or on the contest level when
            # --all is passed.
            if level == 'problem' or (level == 'problemset' and config.args.all):
                success &= latex.build_problem_pdfs(problem)
        if action in ['solutions']:
            if level == 'problem':
                success &= latex.build_problem_pdfs(problem, solutions=True, web=config.args.web)
        if action in ['validate', 'all']:
            if not (action == 'validate' and (config.args.input or config.args.answer)):
                success &= problem.validate_data(validate.Mode.INVALID)
            if not (action == 'validate' and (config.args.answer or config.args.invalid)):
                success &= problem.validate_data(validate.Mode.INPUT)
            if not (action == 'validate' and (config.args.input or config.args.invalid)):
                success &= problem.validate_data(validate.Mode.ANSWER)
        if action in ['run', 'all']:
            success &= problem.run_submissions()
        if action in ['test']:
            config.args.no_bar = True
            success &= problem.test_submissions()
        if action in ['constraints']:
            success &= constraints.check_constraints(problem)
        if action in ['zip']:
            output = problem.path / f'{problem.name}.zip'

            problem_zips.append(output)
            if not config.args.skip:
                # Set up arguments for generate.
                old_args = argparse.Namespace(**vars(config.args))
                config.args.check_deterministic = not config.args.force
                config.args.add = None
                config.args.verbose = 0
                config.args.testcases = None
                config.args.force = False
                success &= generate.generate(problem)
                config.args = old_args

                if not config.args.kattis:
                    # Make sure that all problems use the same language for the PDFs
                    export.force_single_language(problems)

                    success &= latex.build_problem_pdfs(problem)

                if not config.args.force:
                    success &= problem.validate_data(validate.Mode.INPUT, constraints={})
                    success &= problem.validate_data(validate.Mode.ANSWER, constraints={})

                # Write to problemname.zip, where we strip all non-alphanumeric from the
                # problem directory name.
                success &= export.build_problem_zip(problem, output)

        if len(problems) > 1:
            print(file=sys.stderr)

    if action in ['export']:
        # Add contest PDF for only one language to DOMjudge
        statement_language = export.force_single_language(problems)

        export.export_contest_and_problems(problems, statement_language)

    if level == 'problemset':
        print(f'{Style.BRIGHT}CONTEST {contest}{Style.RESET_ALL}', file=sys.stderr)

        # build pdf for the entire contest
        if action in ['pdf']:
            success &= latex.build_contest_pdfs(contest, problems, tmpdir, web=config.args.web)

        if action in ['solutions']:
            success &= latex.build_contest_pdfs(
                contest, problems, tmpdir, solutions=True, web=config.args.web
            )

        if action in ['zip']:
            statement_language = None
            if not config.args.kattis:
                # Add contest/solutions PDF for only one language to the zip file
                statement_language = export.force_single_language(problems)

                success &= latex.build_contest_pdfs(contest, problems, tmpdir, statement_language)
                success &= latex.build_contest_pdfs(
                    contest, problems, tmpdir, statement_language, web=True
                )
                if not config.args.no_solutions:
                    success &= latex.build_contest_pdfs(
                        contest, problems, tmpdir, statement_language, solutions=True
                    )
                    success &= latex.build_contest_pdfs(
                        contest, problems, tmpdir, statement_language, solutions=True, web=True
                    )

            outfile = contest + '.zip'
            if config.args.kattis:
                outfile = contest + '-kattis.zip'
            export.build_contest_zip(problems, problem_zips, outfile, statement_language)
        if action in ['update_problems_yaml']:
            export.update_problems_yaml(
                problems,
                re.split("[^#0-9A-Za-z]", config.args.colors) if config.args.colors else None,
            )

    if not success or config.n_error > 0 or config.n_warn > 0:
        sys.exit(1)


def read_personal_config():
    args = {}

    if is_windows():
        home_config = Path(os.getenv('AppData'))
    else:
        home_config = (
            Path(os.getenv('XDG_CONFIG_HOME'))
            if os.getenv('XDG_CONFIG_HOME')
            else Path(os.getenv('HOME')) / '.config'
        )

    for config_file in [
        # Highest prio: contest directory
        Path() / '.bapctools.yaml',
        Path() / '..' / '.bapctools.yaml',
        # Lowest prio: user config directory
        home_config / 'bapctools' / 'config.yaml',
    ]:
        if not config_file.is_file():
            continue
        config_data = read_yaml(config_file) or {}
        for arg, value in config_data.items():
            if arg not in args:
                args[arg] = value

    return args


# Takes command line arguments
def main():
    def interrupt_handler(sig, frame):
        fatal('Running interrupted')

    signal.signal(signal.SIGINT, interrupt_handler)

    # Don't zero newly allocated memory for this any any subprocess
    # Will likely only work on linux
    os.environ['MALLOC_PERTURB_'] = str(0b01011001)

    parser = build_parser()
    parser.set_defaults(**read_personal_config())
    run_parsed_arguments(parser.parse_args())


if __name__ == '__main__':
    main()


def test(args):
    config.RUNNING_TEST = True

    # Make sure to cd back to the original directory before returning.
    # Needed to stay in the same directory in tests.
    original_directory = Path().cwd()
    config.n_warn = 0
    config.n_error = 0
    contest._contest_yaml = None
    contest._problems_yaml = None
    try:
        parser = build_parser()
        run_parsed_arguments(parser.parse_args(args))
    finally:
        os.chdir(original_directory)
        ProgressBar.current_bar = None
