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
            response = export.call_api('GET', f'/contests/{cid}/problems?public=true')
            response.raise_for_status()
            contest_problems = json.loads(response.text)
            assert isinstance(problems, list)
            for problem in contest_problems:
                solves[problem['id']] = 0

            response = export.call_api('GET', f'/contests/{cid}/scoreboard?public=true')
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
        '--cpp-flags', help='Additional compiler flags used for all c++ compilations.'
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
        '--api',
        help='CCS API endpoint to use, e.g. https://www.domjudge.org/demoweb. Defaults to the value in contest.yaml.',
    )
    global_parser.add_argument('--username', '-u', help='The username to login to the CCS.')
    global_parser.add_argument('--password', '-p', help='The password to login to the CCS.')
    global_parser.add_argument(
        '--cp', action='store_true', help='Copy the output pdf instead of symlinking it.'
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
        choices=['default', 'custom', 'custom interactive'],
    )
    problemparser.add_argument('--skel', help='Skeleton problem directory to copy from.')
    problemparser.add_argument('--language', action='append', help='Statement language')

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
    pdfparser.add_argument('--language', type=str, help='Set statement language.')
    pdfparser.add_argument('--no-timelimit', action='store_true', help='Do not print timelimits.')
    pdfparser.add_argument(
        '--watch',
        '-w',
        action='store_true',
        help='Continuously compile the pdf whenever a `problem_statement.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files.',
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
        help='Continuously compile the pdf whenever a `solution.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files.',
    )
    solparser.add_argument('--web', action='store_true', help='Create a web version of the pdf.')
    solparser.add_argument('-1', action='store_true', help='Only run the LaTeX compiler once.')

    # Validation
    validate_parser = subparsers.add_parser(
        'validate', parents=[global_parser], help='validate all grammar'
    )
    validate_parser.add_argument('testcases', nargs='*', type=Path, help='The testcases to run on.')
    input_output_group = validate_parser.add_mutually_exclusive_group()
    input_output_group.add_argument(
        '--input', '-i', action='store_true', help='Only validate input.'
    )
    input_output_group.add_argument(
        '--output', '-o', action='store_true', help='Only validate output.'
    )

    move_or_remove_group = validate_parser.add_mutually_exclusive_group()
    move_or_remove_group.add_argument(
        '--remove', action='store_true', help='Remove failing testcases.'
    )
    move_or_remove_group.add_argument('--move-to', help='Move failing testcases to this directory.')

    validate_parser.add_argument(
        '--skip-testcase-sanity-checks',
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
        '--force', '-f', action='store_true', help='Overwrite existing input files.'
    )
    genparser.add_argument(
        '--all',
        '-a',
        action='store_true',
        help='Regenerate all data, including up to date test cases. ',
    )
    genparser.add_argument(
        '--check-deterministic',
        action='store_true',
        help='Rerun all generators to make sure generators are deterministic.',
    )
    genparser.add_argument(
        '--timeout', '-t', type=int, help='Override the default timeout. Default: 30.'
    )
    genparser.add_argument(
        '--samples',
        action='store_true',
        help='Overwrite the samples as well, in combination with -f.',
    )

    genparser_group = genparser.add_mutually_exclusive_group()
    genparser_group.add_argument(
        '--add-manual',
        nargs='?',
        type=Path,
        const='generators/manual',
        help='Add manual cases to generators.yaml.',
        metavar='TARGET_DIRECTORY=generators/manual',
    )
    genparser_group.add_argument(
        '--clean', '-C', action='store_true', help='Delete unlisted files.'
    )
    genparser_group.add_argument(
        '--clean-generated', '-c', action='store_true', help='Delete generated files.'
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
        help='The default solution to use for generating .ans files.',
    )
    genparser.add_argument(
        '--ignore-validators',
        action='store_true',
        help='Ignore results of input and output validators. They are still run.',
    )
    genparser.add_argument(
        '--skip-solution',
        action='store_true',
        help='Skip generating .ans/.interaction files with the solution.',
    )
    genparser.add_argument(
        '--skip-visualizer',
        action='store_true',
        help='Skip generating graphics with the visualizer.',
    )
    genparser.add_argument(
        '--skip-testcase-sanity-checks',
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
        '--table', action='store_true', help='Print a submissions x testcases table for analysis.'
    )
    runparser.add_argument(
        '--timeout',
        type=int,
        help='Override the default timeout. Default: 1.5 * timelimit + 1.',
    )
    runparser.add_argument('--timelimit', '-t', type=int, help='Override the default timelimit.')
    runparser.add_argument(
        '--memory',
        '-m',
        help='The max amount of memory in MB a subprocesses may use. Does not work for java. Default: 2048.',
    )
    runparser.add_argument(
        '--force',
        '-f',
        action='store_true',
        help='Allow overwriting existing input files in generator.',
    )
    runparser.add_argument(
        '--skip-testcase-sanity-checks',
        action='store_true',
        help='Skip sanity checks on testcases.',
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
    testparser.add_argument(
        '--memory',
        '-m',
        help='The max amount of memory in MB a subprocesses may use. Does not work for java. Default: 2048.',
    )

    # Sort
    subparsers.add_parser(
        'sort', parents=[global_parser], help='sort the problems for a contest by name'
    )

    # All
    allparser = subparsers.add_parser(
        'all', parents=[global_parser], help='validate input, validate output, and run programs'
    )
    allparser.add_argument('--no-timelimit', action='store_true', help='Do not print timelimits.')
    allparser.add_argument(
        '--cleanup-generated', action='store_true', help='Clean up generated testcases afterwards.'
    )
    allparser.add_argument('--force', '-f', action='store_true', help='Delete all untracked files.')
    allparser.add_argument(
        '--skip-testcase-sanity-checks',
        action='store_true',
        help='Skip sanity checks on testcases.',
    )
    allparser.add_argument(
        '--check-deterministic',
        action='store_true',
        help='Rerun all generators to make sure generators are deterministic.',
    )

    # Build DomJudge zip
    zipparser = subparsers.add_parser(
        'zip', parents=[global_parser], help='Create zip file that can be imported into DomJudge'
    )
    zipparser.add_argument('--skip', action='store_true', help='Skip recreation of problem zips.')
    zipparser.add_argument(
        '--force', '-f', action='store_true', help='Skip validation of input and output files.'
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
    create_slack_channel_parser.add_argument(
        '--token', required=True, help='A user token is of the form xoxp-...'
    )

    join_slack_channel_parser = subparsers.add_parser(
        'join_slack_channels',
        parents=[global_parser],
        help='Join a slack channel for each problem',
    )
    join_slack_channel_parser.add_argument(
        '--token', required=True, help='A user token is of the form xoxp-...'
    )

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

    if config.args.add_manual:
        # Path *must* be inside generators/.
        try:
            config.args.add_manual = (
                (problems[0].path / config.args.add_manual)
                .resolve()
                .relative_to(problems[0].path.resolve())
            )
            config.args.add_manual.relative_to('generators')
        except Exception as e:
            fatal('Directory given to add_manual must match "generators/*".')
        if not (problems[0].path / config.args.add_manual).is_dir():
            fatal(f'"{config.args.add_manual}" not found.')

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
        export.build_samples_zip(problems)
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
        slack.join_slack_channels(problems)
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
            config.args.add_manual = False
            config.args.verbose = 0
            config.args.skip_visualizer = True
            success &= generate.generate(problem)
            config.args = old_args
        if action in ['fuzz']:
            success &= fuzz.fuzz(problem)
        if action in ['pdf', 'all']:
            # only build the pdf on the problem level, or on the contest level when
            # --all is passed.
            if level == 'problem' or (level == 'problemset' and config.args.all):
                success &= latex.build_problem_pdfs(problem)
        if action in ['solutions']:
            if level == 'problem':
                success &= latex.build_problem_pdfs(problem, solutions=True)
        if action in ['validate', 'all']:
            if not (action == 'validate' and config.args.output):
                success &= problem.validate_format('input_format')
        if action in ['validate', 'output', 'all']:
            if not (action == 'validate' and config.args.input):
                success &= problem.validate_format('output_format')
        if action in ['run', 'all']:
            success &= problem.run_submissions()
        if action in ['test']:
            config.args.no_bar = True
            success &= problem.test_submissions()
        if action in ['constraints']:
            success &= constraints.check_constraints(problem)
        if action in ['zip']:
            output = problem.path.with_suffix('.zip')

            problem_zips.append(output)
            if not config.args.skip:

                # Set up arguments for generate.
                old_args = argparse.Namespace(**vars(config.args))
                config.args.check_deterministic = not config.args.force
                config.args.jobs = None
                config.args.add_manual = False
                config.args.verbose = 0
                config.args.testcases = None
                config.args.force = False
                success &= generate.generate(problem)
                config.args = old_args

                success &= latex.build_problem_pdfs(problem)
                if not config.args.force:
                    success &= problem.validate_format('input_format', constraints={})
                    success &= problem.validate_format('output_format', constraints={})

                # Write to problemname.zip, where we strip all non-alphanumeric from the
                # problem directory name.
                success &= export.build_problem_zip(problem, output)
        if action == 'all' and config.args.cleanup_generated:
            success &= generate.cleanup_generated(problem)

        if len(problems) > 1:
            print(file=sys.stderr)

    if action in ['export']:
        export.export_contest_and_problems(problems)

    if level == 'problemset':
        print(f'{Style.BRIGHT}CONTEST {contest}{Style.RESET_ALL}', file=sys.stderr)

        # build pdf for the entire contest
        if action in ['pdf']:
            success &= latex.build_contest_pdfs(contest, problems, tmpdir, web=config.args.web)

        if action in ['solutions']:
            success &= latex.build_contest_pdf(
                contest, problems, tmpdir, solutions=True, web=config.args.web
            )

        if action in ['zip']:
            if not config.args.kattis:
                success &= latex.build_contest_pdf(contest, problems, tmpdir)
                success &= latex.build_contest_pdf(contest, problems, tmpdir, web=True)
                if not config.args.no_solutions:
                    success &= latex.build_contest_pdf(contest, problems, tmpdir, solutions=True)
                    success &= latex.build_contest_pdf(
                        contest, problems, tmpdir, solutions=True, web=True
                    )

            outfile = contest + '.zip'
            if config.args.kattis:
                outfile = contest + '-kattis.zip'
            export.build_contest_zip(problems, problem_zips, outfile, config.args)
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
