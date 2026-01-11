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
import re
import shutil
import signal
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import colorama
from colorama import Style

# Local imports
from bapctools import (
    config,
    constraints,
    contest,
    download_submissions,
    export,
    fuzz,
    generate,
    latex,
    skel,
    slack,
    solve_stats,
    stats,
    upgrade,
    validate,
)
from bapctools.contest import call_api_get_json, contest_yaml, get_contest_id, problems_yaml
from bapctools.problem import Problem
from bapctools.util import (
    AbortException,
    ask_variable_bool,
    eprint,
    error,
    fatal,
    glob,
    inc_label,
    is_problem_directory,
    is_relative_to,
    is_windows,
    log,
    ProgressBar,
    read_yaml,
    resolve_path_argument,
    verbose,
    warn,
    write_yaml,
)

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
if not os.getenv("GITLAB_CI", False) and not os.getenv("CI", False):
    colorama.init()

# List of high level todos:
# TODO: Do more things in parallel (e.g. building validators/generators/submissions).
# TODO: Get rid of old problem.path and settings objects in cli.py.
#       This mostly needs changes in the less frequently used subcommands.

if sys.version_info < (3, 10):
    fatal("BAPCtools requires at least Python 3.10.")


# Changes the working directory to the root of the contest.
# sets the "level" of the current command (either 'problem' or 'problemset')
# and, if `level == 'problem'` returns the directory of the problem.
def change_directory() -> Optional[Path]:
    problem_dir: Optional[Path] = None
    config.level = "problemset"
    if config.args.contest:
        contest_dir = config.args.contest.absolute()
        os.chdir(contest_dir)
    if config.args.problem:
        problem_dir = config.args.problem.absolute()
    elif is_problem_directory(Path.cwd()):
        problem_dir = Path.cwd().absolute()
    if problem_dir is not None:
        config.level = "problem"
        os.chdir(problem_dir.parent)
    return problem_dir


# Get the list of relevant problems.
# Either use the problems.yaml,
# or check the existence of problem.yaml and sort by shortname.
def get_problems(problem_dir: Optional[Path]) -> tuple[list[Problem], Path]:
    # We create one tmpdir per contest.
    h = hashlib.sha256(bytes(Path.cwd())).hexdigest()[-6:]
    tmpdir = Path(tempfile.gettempdir()) / ("bapctools_" + h)
    tmpdir.mkdir(parents=True, exist_ok=True)

    def fallback_problems() -> list[tuple[Path, str]]:
        problem_paths = list(filter(is_problem_directory, glob(Path("."), "*/")))
        label = chr(ord("Z") - len(problem_paths) + 1) if contest_yaml().test_session else "A"
        problems = []
        for path in problem_paths:
            problems.append((path, label))
            label = inc_label(label)
        return problems

    problems = []
    if config.level == "problem":
        assert problem_dir
        # If the problem is mentioned in problems.yaml, use that ID.
        for p in problems_yaml():
            if p.id == problem_dir.name:
                problems = [Problem(Path(problem_dir.name), tmpdir, p.label)]
                break

        if not problems:
            for path, label in fallback_problems():
                if path.name == problem_dir.name:
                    problems = [Problem(Path(problem_dir.name), tmpdir, label)]
                    break
    else:
        assert config.level == "problemset"
        # If problems.yaml is available, use it.
        if problems_yaml():
            problems = [Problem(Path(p.id), tmpdir, p.label) for p in problems_yaml()]
        else:
            # Otherwise, fallback to all directories with a problem.yaml and sort by shortname.
            problems = [Problem(path, tmpdir, label) for path, label in fallback_problems()]
            if len(problems) == 0:
                fatal("Did not find problem.yaml. Are you running this from a problem directory?")

        if config.args.action == "solutions":
            order = config.args.order or contest_yaml().order
            if order is not None:
                labels = {p.label for p in problems}
                counts = Counter(order)
                for id, count in counts.items():
                    if id not in labels:
                        append_s = "s" if count != 1 else ""
                        warn(f"Unknown {id} appears {count} time{append_s} in 'order'")
                    elif count > 1:
                        warn(f"{id} appears {count} times in 'order'")
                for problem in problems:
                    if problem.label not in counts:
                        warn(f"{problem.label} does not appear in 'order'")

                # Sort by position of id in order
                def get_pos(id: Optional[str]) -> int:
                    if id and id in order:
                        return order.index(id)
                    else:
                        return len(order)

                problems.sort(key=lambda p: (get_pos(p.label), p.label, p.name))

            if config.args.order_from_ccs:
                # Sort by increasing difficulty, extracted from the CCS api.
                class ProblemStat:
                    def __init__(self) -> None:
                        self.solved = 0
                        self.submissions = 0
                        self.pending = 0
                        self.teams_submitted = 0
                        self.teams_pending = 0

                    def update(self, team_stats: dict[str, Any]) -> None:
                        if team_stats["solved"]:
                            self.solved += 1
                        if team_stats["num_judged"]:
                            self.submissions += team_stats["num_judged"]
                            self.teams_submitted += 1
                        if team_stats["num_pending"]:
                            self.pending += team_stats["num_pending"]
                            self.teams_pending += 1

                    def key(self) -> tuple[int, int]:
                        # self.solved more AC => easier
                        # possible tie breakers:
                        # self.submissions more needed to get the same number of AC => Harder
                        # self.teams_pending more teams tried => appeared easier
                        # TODO: consider more stats?
                        return (-self.solved, self.submissions)

                # Get active contest.
                cid = get_contest_id()

                # Read set of problems
                contest_problems = call_api_get_json(f"/contests/{cid}/problems?public=true")
                assert isinstance(problems, list)

                problem_stats = {problem["id"]: ProblemStat() for problem in contest_problems}

                scoreboard = call_api_get_json(f"/contests/{cid}/scoreboard?public=true")

                for team in scoreboard["rows"]:
                    for team_stats in team["problems"]:
                        problem_stats[team_stats["problem_id"]].update(team_stats)

                # Sort the problems
                problems.sort(key=lambda p: (problem_stats[p.name].key(), p.label))
                verbose(f"order: {', '.join(map(lambda p: str(p.label), problems))}")

                if ask_variable_bool("Update order in contest.yaml"):
                    contest_yaml_path = Path("contest.yaml")
                    data = read_yaml(contest_yaml_path) or {}
                    if not isinstance(data, dict):
                        error("could not parse contest.yaml.")
                    else:
                        data["order"] = "".join(p.label or p.name for p in problems)
                        write_yaml(data, contest_yaml_path)
                        log("Updated order")

    # Filter problems by submissions/testcases, if given.
    if config.level == "problemset" and (config.args.submissions or config.args.testcases):
        submissions = config.args.submissions or []
        testcases = config.args.testcases or []

        def keep_problem(problem: Problem) -> bool:
            for s in submissions:
                x = resolve_path_argument(problem, s, "submissions")
                if x:
                    if is_relative_to(problem.path, x):
                        return True
            for t in testcases:
                x = resolve_path_argument(problem, t, "data", suffixes=[".in"])
                if x:
                    if is_relative_to(problem.path, x):
                        return True
            return False

        problems = [p for p in problems if keep_problem(p)]

    return problems, tmpdir


# NOTE: This is one of the few places that prints to stdout instead of stderr.
def print_sorted(problems: list[Problem]) -> None:
    for problem in problems:
        print(f"{problem.label:<2}: {problem.path}")


def split_submissions_and_testcases(s: list[Path]) -> tuple[list[Path], list[Path]]:
    # We try to identify testcases by common directory names and common suffixes
    submissions = []
    testcases = []
    for p in s:
        testcase_dirs = ["data", "sample", "secret", "fuzz", "testing_tool_cases"]
        if (
            any(part in testcase_dirs for part in p.parts)
            or p.suffix in config.KNOWN_DATA_EXTENSIONS
        ):
            # Strip potential suffix
            if p.suffix in config.KNOWN_DATA_EXTENSIONS:
                p = p.with_suffix("")
            testcases.append(p)
        else:
            submissions.append(p)
    return (submissions, testcases)


# We set argument_default=SUPPRESS in all parsers,
# to make sure no default values (like `False` or `0`) end up in the parsed arguments object.
# If we would not do this, it would not be possible to check which keys are explicitly set from the command line.
# This check is necessary when loading the personal config file in `read_personal_config`.
class SuppressingParser(argparse.ArgumentParser):
    def __init__(self, **kwargs: Any) -> None:
        super(SuppressingParser, self).__init__(**kwargs, argument_default=argparse.SUPPRESS)


def build_parser() -> SuppressingParser:
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
        "--verbose",
        "-v",
        action="count",
        help="Verbose output; once for what's going on, twice for all intermediate output.",
    )
    group = global_parser.add_mutually_exclusive_group()
    group.add_argument("--contest", type=Path, help="Path to the contest to use.")
    group.add_argument(
        "--problem",
        type=Path,
        help="Path to the problem to use. Can be relative to contest if given.",
    )

    global_parser.add_argument(
        "--no-bar",
        action="store_true",
        help="Do not show progress bars in non-interactive environments.",
    )
    global_parser.add_argument(
        "--error",
        "-e",
        action="store_true",
        help="Print full error of failing commands and some succeeding commands.",
    )
    global_parser.add_argument(
        "--force-build",
        action="store_true",
        help="Force rebuild instead of only on changed files.",
    )
    global_parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        help="The number of jobs to use. Default: cpu_count()/2.",
    )
    global_parser.add_argument(
        "--memory",
        "-m",
        type=int,
        help="The maximum amount of memory in MB a subprocess may use.",
    )
    global_parser.add_argument(
        "--api",
        help="CCS API endpoint to use, e.g. https://www.domjudge.org/demoweb. Defaults to the value in contest.yaml.",
    )
    global_parser.add_argument("--username", "-u", help="The username to login to the CCS.")
    global_parser.add_argument("--password", "-p", help="The password to login to the CCS.")
    global_parser.add_argument(
        "--cp",
        action="store_true",
        help="Copy the output pdf instead of symlinking it.",
    )
    global_parser.add_argument("--lang", nargs="+", help="Languages to include.")

    subparsers = parser.add_subparsers(
        title="actions", dest="action", parser_class=SuppressingParser, required=True
    )

    # upgrade
    subparsers.add_parser(
        "upgrade",
        parents=[global_parser],
        help="Upgrade a problem or contest.",
    )

    # New contest
    contestparser = subparsers.add_parser(
        "new_contest",
        parents=[global_parser],
        help="Add a new contest to the current directory.",
    )
    contestparser.add_argument("contestname", nargs="?", help="The name of the contest")

    # New problem
    problemparser = subparsers.add_parser(
        "new_problem",
        parents=[global_parser],
        help="Add a new problem to the current directory.",
    )
    problemparser.add_argument("problemname", nargs="?", help="The name of the problem,")
    problemparser.add_argument("--author", help="The author of the problem,")
    problemparser.add_argument(
        "--type",
        help="The type of the problem.",
        choices=[
            "pass-fail",
            "float",
            "custom",
            "interactive",
            "multi-pass",
            "interactive multi-pass",
        ],
    )
    problemparser.add_argument("--skel", help="Skeleton problem directory to copy from.")
    problemparser.add_argument(
        "--defaults",
        action="store_true",
        help="Assume the defaults for fields not passed as arguments."
        + " This skips input-prompts but fails when defaults cannot be assumed.",
    )

    # Copy directory from skel.
    skelparser = subparsers.add_parser(
        "skel",
        parents=[global_parser],
        help="Copy the given directories from skel to the current problem directory.",
    )
    skelparser.add_argument(
        "directory",
        nargs="+",
        type=Path,
        help="Directories to copy from skel/problem/, relative to the problem directory.",
    )
    skelparser.add_argument("--skel", help="Skeleton problem directory to copy from.")

    # Rename problem
    renameproblemparser = subparsers.add_parser(
        "rename_problem",
        parents=[global_parser],
        help="Rename a problem, including its directory.",
    )
    renameproblemparser.add_argument("problemname", nargs="?", help="The new name of the problem,")

    # Problem statements
    pdfparser = subparsers.add_parser(
        "pdf", parents=[global_parser], help="Build the problem statement pdf."
    )
    pdfparser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Create problem statements for individual problems as well.",
    )
    pdfparser.add_argument("--no-time-limit", action="store_true", help="Do not print timelimits.")
    pdfparser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Continuously compile the pdf whenever a `problem.*.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files. Further Note that this implies `--cp`.",
    )
    pdfparser.add_argument(
        "--open",
        "-o",
        nargs="?",
        const=True,
        type=Path,
        help="Open the continuously compiled pdf (with a specified program).",
    )
    pdfparser.add_argument("--web", action="store_true", help="Create a web version of the pdf.")
    pdfparser.add_argument("-1", action="store_true", help="Only run the LaTeX compiler once.")
    pdfparser.add_argument("--tex-command", help="TeX command to use, default: pdflatex")

    # Problem slides
    slidesparser = subparsers.add_parser(
        "problem_slides", parents=[global_parser], help="Build the problem slides pdf."
    )
    slidesparser.add_argument(
        "--no-time-limit", action="store_true", help="Do not print timelimits."
    )
    slidesparser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Continuously compile the pdf whenever a `problem-slide.*.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files.",
    )
    slidesparser.add_argument(
        "--open",
        "-o",
        nargs="?",
        const=True,
        type=Path,
        help="Open the continuously compiled pdf (with a specified program).",
    )
    slidesparser.add_argument("-1", action="store_true", help="Only run the LaTeX compiler once.")
    slidesparser.add_argument("--tex-command", help="TeX command to use, default: pdflatex")

    # Solution slides
    solparser = subparsers.add_parser(
        "solutions", parents=[global_parser], help="Build the solution slides pdf."
    )
    orderparser = solparser.add_mutually_exclusive_group()
    orderparser.add_argument(
        "--order", action="store", help='The order of the problems, e.g.: "CAB"'
    )
    orderparser.add_argument(
        "--order-from-ccs",
        action="store_true",
        help="Order the problems by increasing difficulty, extracted from the CCS.",
    )
    solparser.add_argument(
        "--contest-id",
        action="store",
        help="Contest ID to use when reading from the API. Only useful with --order-from-ccs. Defaults to value of contest_id in contest.yaml.",
    )
    solparser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Continuously compile the pdf whenever a `solution.*.tex` changes. Note that this does not pick up changes to `*.yaml` configuration files. Further Note that this implies `--cp`.",
    )
    solparser.add_argument(
        "--open",
        "-o",
        nargs="?",
        const=True,
        type=Path,
        help="Open the continuously compiled pdf  (with a specified program).",
    )
    solparser.add_argument("--web", action="store_true", help="Create a web version of the pdf.")
    solparser.add_argument("-1", action="store_true", help="Only run the LaTeX compiler once.")
    solparser.add_argument("--tex-command", help="TeX command to use, default: pdflatex")

    # Validation
    validate_parser = subparsers.add_parser(
        "validate", parents=[global_parser], help="validate all grammar"
    )
    validate_parser.add_argument("testcases", nargs="*", type=Path, help="The testcases to run on.")
    validation_group = validate_parser.add_mutually_exclusive_group()
    validation_group.add_argument("--input", "-i", action="store_true", help="Only validate input.")
    validation_group.add_argument("--answer", action="store_true", help="Only validate answer.")
    validation_group.add_argument(
        "--invalid", action="store_true", help="Only check invalid files for validity."
    )
    validation_group.add_argument(
        "--generic",
        choices=["invalid_input", "invalid_answer", "invalid_output", "valid_output"],
        nargs="*",
        help="Generate generic (in)valid files based on the first three samples and validate them.",
    )
    validation_group.add_argument(
        "--valid-output",
        action="store_true",
        help="Only check files in 'data/valid_output' for validity.",
    )

    move_or_remove_group = validate_parser.add_mutually_exclusive_group()
    move_or_remove_group.add_argument(
        "--remove", action="store_true", help="Remove failing testcases."
    )
    move_or_remove_group.add_argument("--move-to", help="Move failing testcases to this directory.")

    validate_parser.add_argument(
        "--no-testcase-sanity-checks",
        action="store_true",
        help="Skip sanity checks on testcases.",
    )
    validate_parser.add_argument(
        "--timeout", "-t", type=int, help="Override the default timeout. Default: 30."
    )

    # constraints validation
    constraintsparser = subparsers.add_parser(
        "constraints",
        parents=[global_parser],
        help="prints all the constraints found in problemset and validators",
    )
    constraintsparser.add_argument(
        "--no-generate", "-G", action="store_true", help="Do not run `generate`."
    )

    # Stats
    statsparser = subparsers.add_parser(
        "stats", parents=[global_parser], help="show statistics for contest/problem"
    )
    all_stats_group = statsparser.add_mutually_exclusive_group()
    all_stats_group.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Print all stats",
    )

    # Generate Testcases
    genparser = subparsers.add_parser(
        "generate",
        parents=[global_parser],
        help="Generate testcases according to .gen files.",
    )
    genparser.add_argument(
        "--check-deterministic",
        action="store_true",
        help="Rerun all generators to make sure generators are deterministic.",
    )
    genparser.add_argument(
        "--timeout", "-t", type=int, help="Override the default timeout. Default: 30."
    )

    genparser_group = genparser.add_mutually_exclusive_group()
    genparser_group.add_argument(
        "--add",
        nargs="*",
        type=Path,
        help="Add case(s) to generators.yaml.",
        metavar="TARGET_DIRECTORY=generators/manual",
    )
    genparser_group.add_argument(
        "--clean", "-C", action="store_true", help="Delete all cached files."
    )
    genparser_group.add_argument(
        "--reorder",
        action="store_true",
        help="Reorder cases by difficulty inside the given directories.",
    )

    genparser.add_argument(
        "--interaction",
        "-i",
        action="store_true",
        help="Use the solution to generate .interaction files.",
    )
    genparser.add_argument(
        "testcases",
        nargs="*",
        type=Path,
        help="The testcases to generate, given as directory, .in/.ans file, or base name.",
    )
    genparser.add_argument(
        "--default-solution",
        "-s",
        type=Path,
        help="The default solution to use for generating .ans files. Not compatible with generator.yaml.",
    )
    genparser.add_argument(
        "--no-validators",
        default=False,
        action="store_true",
        help="Ignore results of input and answer validation. Validators are still run.",
    )
    genparser.add_argument(
        "--no-solution",
        default=False,
        action="store_true",
        help="Skip generating .ans/.interaction files with the solution.",
    )
    genparser.add_argument(
        "--no-visualizer",
        default=False,
        action="store_true",
        help="Skip generating graphics with the visualizer.",
    )
    genparser.add_argument(
        "--no-testcase-sanity-checks",
        default=False,
        action="store_true",
        help="Skip sanity checks on testcases.",
    )

    # Fuzzer
    fuzzparser = subparsers.add_parser(
        "fuzz",
        parents=[global_parser],
        help="Generate random testcases and search for inconsistencies in AC submissions.",
    )
    fuzzparser.add_argument("--time", type=int, help="Number of seconds to run for. Default: 600")
    fuzzparser.add_argument("--time-limit", "-t", type=float, help="Time limit for submissions.")
    fuzzparser.add_argument(
        "submissions",
        nargs="*",
        type=Path,
        help="The generator.yaml rules to use, given as directory, .in/.ans file, or base name, and submissions to run.",
    )
    fuzzparser.add_argument(
        "--timeout", type=int, help="Override the default timeout. Default: 30."
    )

    # Run
    runparser = subparsers.add_parser(
        "run",
        parents=[global_parser],
        help="Run multiple programs against some or all input.",
    )
    runparser.add_argument(
        "submissions",
        nargs="*",
        type=Path,
        help="optionally supply a list of programs and testcases to run",
    )
    runparser.add_argument("--samples", action="store_true", help="Only run on the samples.")
    runparser.add_argument(
        "--no-generate",
        "-G",
        action="store_true",
        help="Do not run `generate` before running submissions.",
    )
    runparser.add_argument(
        "--visualizer",
        dest="no_visualizer",
        action="store_false",
        help="Also run the output visualizer.",
    )
    runparser.add_argument(
        "--all",
        "-a",
        action="count",
        default=0,
        help="Run all testcases. Use twice to continue even after timeouts.",
    )
    runparser.add_argument(
        "--default-solution",
        "-s",
        type=Path,
        help="The default solution to use for generating .ans files. Not compatible with generators.yaml.",
    )
    runparser.add_argument(
        "--table",
        action="store_true",
        help="Print a submissions x testcases table for analysis.",
    )
    runparser.add_argument(
        "--overview",
        "-o",
        action="store_true",
        help="Print a live overview for the judgings.",
    )
    runparser.add_argument("--tree", action="store_true", help="Show a tree of verdicts.")

    runparser.add_argument("--depth", type=int, help="Depth of verdict tree.")
    runparser.add_argument(
        "--timeout",
        type=int,
        help="Override the default timeout. Default: 1.5 * time_limit + 1.",
    )
    runparser.add_argument(
        "--time-limit", "-t", type=float, help="Override the default time-limit."
    )
    runparser.add_argument(
        "--no-testcase-sanity-checks",
        action="store_true",
        help="Skip sanity checks on testcases.",
    )
    runparser.add_argument(
        "--sanitizer",
        action="store_true",
        help="Run submissions with additional sanitizer flags (currently only C++). Note that this removes all memory limits for submissions.",
    )

    timelimitparser = subparsers.add_parser(
        "time_limit",
        parents=[global_parser],
        help="Determine the time limit for a problem.",
    )
    timelimitparser.add_argument(
        "submissions",
        nargs="*",
        type=Path,
        help="optionally supply a list of programs and testcases on which the time limit should be based.",
    )
    timelimitparser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Run all submissions, not only AC and TLE.",
    )
    timelimitparser.add_argument(
        "--write",
        "-w",
        action="store_true",
        help="Write .timelimit file.",
    )
    timelimitparser.add_argument(
        "--timeout", "-t", type=int, help="Override the default timeout. Default: 60."
    )
    timelimitparser.add_argument(
        "--no-generate", "-G", action="store_true", help="Do not run `generate`."
    )

    # Test
    testparser = subparsers.add_parser(
        "test",
        parents=[global_parser],
        help="Run a single program and print the output.",
    )
    testparser.add_argument("submissions", nargs=1, type=Path, help="A single submission to run")
    testcasesgroup = testparser.add_mutually_exclusive_group()
    testcasesgroup.add_argument(
        "testcases",
        nargs="*",
        default=[],
        type=Path,
        help="Optionally a list of testcases to run on.",
    )
    testcasesgroup.add_argument("--samples", action="store_true", help="Only run on the samples.")
    testcasesgroup.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Run submission in interactive mode: stdin is from the command line.",
    )
    testparser.add_argument(
        "--timeout",
        type=int,
        help="Override the default timeout. Default: 1.5 * time_limit + 1.",
    )

    checktestingtool = subparsers.add_parser(
        "check_testing_tool",
        parents=[global_parser],
        help="Run testing_tool against some or all accepted submissions.",
    )
    checktestingtool.add_argument(
        "submissions",
        nargs="*",
        type=Path,
        help="optionally supply a list of programs and testcases to run",
    )
    checktestingtool.add_argument(
        "--no-generate",
        "-G",
        action="store_true",
        help="Do not run `generate` before running submissions.",
    )
    checktestingtool.add_argument(
        "--timeout",
        type=int,
        help="Override the default timeout. Default: 1.5 * time_limit + 1.",
    )
    checktestingtool.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Run all testcases and don't stop on error.",
    )

    # Sort
    subparsers.add_parser(
        "sort", parents=[global_parser], help="sort the problems for a contest by name"
    )

    # All
    allparser = subparsers.add_parser(
        "all",
        parents=[global_parser],
        help="validate input, validate answers, and run programs",
    )
    allparser.add_argument("--no-time-limit", action="store_true", help="Do not print time limits.")
    allparser.add_argument(
        "--no-testcase-sanity-checks",
        action="store_true",
        help="Skip sanity checks on testcases.",
    )
    allparser.add_argument(
        "--check-deterministic",
        action="store_true",
        help="Rerun all generators to make sure generators are deterministic.",
    )
    allparser.add_argument(
        "--timeout", "-t", type=int, help="Override the default timeout. Default: 30."
    )
    allparser.add_argument(
        "--overview",
        "-o",
        action="store_true",
        help="Print a live overview for the judgings.",
    )

    # Build DOMjudge zip
    zipparser = subparsers.add_parser(
        "zip",
        parents=[global_parser],
        help="Create zip file that can be imported into DOMjudge",
    )
    zipparser.add_argument("--skip", action="store_true", help="Skip recreation of problem zips.")
    zipparser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Skip validation of input and answers.",
    )
    zipparser.add_argument(
        "--no-generate", "-G", action="store_true", help="Skip generation of test cases."
    )
    zipparser.add_argument(
        "--kattis",
        action="store_true",
        help="Make a zip more following the kattis problemarchive.com format.",
    )
    zipparser.add_argument(
        "--legacy",
        action="store_true",
        help="Make a zip more following the legacy format.",
    )
    zipparser.add_argument("--no-solutions", action="store_true", help="Do not compile solutions")

    # Build a zip with all samples.
    samplezipparser = subparsers.add_parser(
        "samplezip", parents=[global_parser], help="Create zip file of all samples."
    )
    samplezipparser.add_argument(
        "--legacy",
        action="store_true",
        help="Make a zip more following the legacy format.",
    )

    gitlab_parser = subparsers.add_parser(
        "gitlabci", parents=[global_parser], help="Print a list of jobs for the given contest."
    )
    gitlab_parser.add_argument(
        "--latest-bt", action="store_true", help="Cache the latest version of BAPCtools."
    )

    forgejo_parser = subparsers.add_parser(
        "forgejo_actions",
        parents=[global_parser],
        help="Setup Forgejo Actions workflows in .forgejo.",
    )
    forgejo_parser.add_argument(
        "--latest-bt", action="store_true", help="Cache the latest version of BAPCtools."
    )

    github_parser = subparsers.add_parser(
        "github_actions",
        parents=[global_parser],
        help="Setup Github Actions workflows in .github.",
    )
    github_parser.add_argument(
        "--latest-bt", action="store_true", help="Cache the latest version of BAPCtools."
    )

    exportparser = subparsers.add_parser(
        "export",
        parents=[global_parser],
        help="Export the problem or contest to DOMjudge.",
    )
    exportparser.add_argument(
        "--contest-id",
        action="store",
        help="Contest ID to use when writing to the API. Defaults to value of contest_id in contest.yaml.",
    )
    exportparser.add_argument(
        "--legacy",
        action="store_true",
        help="Make export more following the legacy format.",
    )

    updateproblemsyamlparser = subparsers.add_parser(
        "update_problems_yaml",
        parents=[global_parser],
        help="Update the problems.yaml with current names and time limits.",
    )
    updateproblemsyamlparser.add_argument(
        "--colors",
        help="Set the colors of the problems. Comma-separated list of hex-codes.",
    )
    updateproblemsyamlparser.add_argument(
        "--sort",
        action="store_true",
        help="Sort the problems by id.",
    )
    updateproblemsyamlparser.add_argument(
        "--number",
        action="store_true",
        help="Use Sxx as problem labels.",
    )
    updateproblemsyamlparser.add_argument(
        "--legacy",
        action="store_true",
        help="Make problems.yaml more following the legacy format.",
    )

    # Print the corresponding temporary directory.
    tmpparser = subparsers.add_parser(
        "tmp",
        parents=[global_parser],
        help="Print the tmpdir corresponding to the current problem.",
    )
    tmpparser.add_argument(
        "--clean",
        "-C",
        action="store_true",
        help="Delete the temporary cache directory for the current problem/contest.",
    )

    solvestatsparser = subparsers.add_parser(
        "solve_stats",
        parents=[global_parser],
        help="Make solve stats plots using Matplotlib. All teams on the public scoreboard are included (including spectator/company teams).",
    )
    solvestatsparser.add_argument(
        "--contest-id",
        action="store",
        help="Contest ID to use when reading from the API. Defaults to value of contest_id in contest.yaml.",
    )
    solvestatsparser.add_argument(
        "--post-freeze",
        action="store_true",
        help="When given, the solve stats will include submissions from after the scoreboard freeze.",
    )

    download_submissions_parser = subparsers.add_parser(
        "download_submissions",
        parents=[global_parser],
        help="Download all submissions for a contest and write them to submissions/.",
    )
    download_submissions_parser.add_argument(
        "--contest-id",
        action="store",
        help="Contest ID to use when reading from the API. Defaults to value of contest_id in contest.yaml.",
    )

    create_slack_channel_parser = subparsers.add_parser(
        "create_slack_channels",
        parents=[global_parser],
        help="Create a slack channel for each problem",
    )
    create_slack_channel_parser.add_argument("--token", help="A user token is of the form xoxp-...")

    join_slack_channel_parser = subparsers.add_parser(
        "join_slack_channels",
        parents=[global_parser],
        help="Join a slack channel for each problem",
    )
    join_slack_channel_parser.add_argument("--token", help="A bot/user token is of the form xox...")
    join_slack_channel_parser.add_argument("username", help="Slack username")

    if not is_windows():
        argcomplete.autocomplete(parser)

    return parser


def find_home_config_dir() -> Optional[Path]:
    if is_windows():
        app_data = os.getenv("AppData")
        return Path(app_data) if app_data else None
    else:
        home = os.getenv("HOME")
        xdg_config_home = os.getenv("XDG_CONFIG_HOME")
        return (
            Path(xdg_config_home) if xdg_config_home else Path(home) / ".config" if home else None
        )


def read_personal_config(problem_dir: Optional[Path]) -> None:
    home_config_dir = find_home_config_dir()
    # possible config files, sorted by priority
    config_files = []
    if problem_dir:
        config_files.append(problem_dir / ".bapctools.yaml")
    config_files.append(Path.cwd() / ".bapctools.yaml")
    if home_config_dir:
        config_files.append(home_config_dir / "bapctools" / "config.yaml")

    for config_file in config_files:
        if not config_file.is_file():
            continue

        config_data = read_yaml(config_file)
        if not config_data:
            continue
        if not isinstance(config_data, dict):
            warn(f"invalid data in {config_data}. SKIPPED.")
            continue

        config.args.add_if_not_set(config.ARGS(config_file, **config_data))


def run_parsed_arguments(args: argparse.Namespace, personal_config: bool = True) -> None:
    # Don't zero newly allocated memory for this and any subprocess
    # Will likely only have an effect on linux
    os.environ["MALLOC_PERTURB_"] = str(0b01011001)

    # Process arguments
    config.args = config.ARGS("args", **vars(args))

    # cd to contest directory
    call_cwd = Path.cwd().absolute()
    problem_dir = change_directory()
    level = config.level
    contest_name = Path.cwd().name

    if personal_config:
        read_personal_config(problem_dir)

    action = config.args.action

    # upgrade commands.
    if action == "upgrade":
        upgrade.upgrade(problem_dir)
        return

    # Skel commands.
    if action == "new_contest":
        os.chdir(call_cwd)
        skel.new_contest()
        return

    if action == "new_problem":
        os.chdir(call_cwd)
        skel.new_problem()
        return

    # get problems list
    problems, tmpdir = get_problems(problem_dir)

    # Split submissions and testcases when needed.
    if action in ["run", "fuzz", "time_limit", "check_testing_tool"]:
        if config.args.submissions:
            config.args.submissions, config.args.testcases = split_submissions_and_testcases(
                config.args.submissions
            )
        else:
            config.args.testcases = []

    # Check non unique uuid
    # TODO: check this even more globally?
    uuids: dict[str, Problem] = {}
    for p in problems:
        if p.settings.uuid in uuids:
            warn(f"{p.name} has the same uuid as {uuids[p.settings.uuid].name}")
        else:
            uuids[p.settings.uuid] = p

    # Check for incompatible actions at the problem/problemset level.
    if level != "problem":
        if action == "test":
            fatal("Testing a submission only works for a single problem.")
        if action == "skel":
            fatal("Copying skel directories only works for a single problem.")

    if action != "generate" and config.args.testcases and config.args.samples:
        fatal("--samples can not go together with an explicit list of testcases.")

    if config.args.add is not None:
        # default to 'generators/manual'
        if len(config.args.add) == 0:
            config.args.add = [Path("generators/manual")]

        # Paths *must* be inside generators/.
        checked_paths = []
        for path in config.args.add:
            if path.parts[0] != "generators":
                warn(f'Path {path} does not match "generators/*". Skipping.')
            else:
                checked_paths.append(path)
        config.args.add = checked_paths

    if config.args.reorder:
        # default to 'data/secret'
        if not config.args.testcases:
            config.args.testcases = [Path("data/secret")]

        # Paths *must* be inside data/.
        checked_paths = []
        for path in config.args.testcases:
            if path.parts[0] != "data":
                warn(f'Path {path} does not match "data/*". Skipping.')
            else:
                checked_paths.append(path)
        config.args.testcases = checked_paths

    # Handle one-off subcommands.
    if action == "tmp":
        if level == "problem":
            level_tmpdir = tmpdir / problems[0].name
        else:
            level_tmpdir = tmpdir

        if config.args.clean:
            log(f"Deleting {tmpdir}!")
            if level_tmpdir.is_dir():
                shutil.rmtree(level_tmpdir)
            if level_tmpdir.is_file():
                level_tmpdir.unlink()
        else:
            eprint(level_tmpdir)

        return

    if action == "stats":
        stats.stats(problems)
        return

    if action == "sort":
        print_sorted(problems)
        return

    if action == "samplezip":
        sampleout = Path("samples.zip")
        if level == "problem":
            sampleout = problems[0].path / sampleout
        languages = export.select_languages(problems)
        export.build_samples_zip(problems, sampleout, languages)
        return

    if action == "rename_problem":
        if level == "problemset":
            fatal("rename_problem only works for a problem")
        skel.rename_problem(problems[0])
        return

    if action == "gitlabci":
        skel.create_gitlab_jobs(contest_name, problems)
        return

    if action == "forgejo_actions":
        skel.create_forgejo_actions(contest_name, problems)
        return

    if action == "github_actions":
        skel.create_github_actions(contest_name, problems)
        return

    if action == "skel":
        skel.copy_skel_dir(problems)
        return

    if action == "solve_stats":
        if level == "problem":
            fatal("solve_stats only works for a contest")
        config.args.jobs = (os.cpu_count() or 1) // 2
        solve_stats.generate_solve_stats(config.args.post_freeze)
        return

    if action == "download_submissions":
        if level == "problem":
            fatal("download_submissions only works for a contest")
        download_submissions.download_submissions()
        return

    if action == "create_slack_channels":
        slack.create_slack_channels(problems)
        return

    if action == "join_slack_channels":
        assert config.args.username is not None
        slack.join_slack_channels(problems, config.args.username)
        return

    problem_zips = []

    success = True

    for problem in problems:
        if (
            level == "problemset"
            and action in ["pdf", "export", "update_problems_yaml"]
            and not config.args.all
        ):
            continue
        eprint(Style.BRIGHT, "PROBLEM ", problem.name, Style.RESET_ALL, sep="")

        if action in ["generate"]:
            success &= generate.generate(problem)
        if (
            action in ["all", "constraints", "run", "time_limit", "check_testing_tool"]
            and not config.args.no_generate
        ):
            # Call `generate` with modified arguments.
            old_args = config.args.copy()
            config.args.jobs = (os.cpu_count() or 1) // 2
            config.args.add = None
            config.args.verbose = 0
            config.args.no_visualizer = True
            success &= generate.generate(problem)
            config.args = old_args
        if action in ["fuzz"]:
            success &= fuzz.Fuzz(problem).run()
        if action in ["pdf", "all"]:
            # only build the pdf on the problem level, or on the contest level when
            # --all is passed.
            if level == "problem" or (level == "problemset" and config.args.all):
                success &= latex.build_problem_pdfs(problem)
        if level == "problem":
            if action in ["solutions"]:
                success &= latex.build_problem_pdfs(
                    problem, build_type=latex.PdfType.SOLUTION, web=config.args.web
                )
            if action in ["problem_slides"]:
                success &= latex.build_problem_pdfs(
                    problem, build_type=latex.PdfType.PROBLEM_SLIDE, web=config.args.web
                )
        if action in ["validate", "all"]:
            # if nothing is specified run all
            specified = any(
                [
                    config.args.invalid,
                    config.args.generic is not None,
                    config.args.input,
                    config.args.answer,
                    config.args.valid_output,
                ]
            )
            if action == "all" or not specified or config.args.invalid:
                success &= problem.validate_data(validate.Mode.INVALID)
            if action == "all" or not specified or config.args.generic is not None:
                if config.args.generic is None:
                    config.args.generic = [
                        "invalid_input",
                        "invalid_answer",
                        "invalid_output",
                        "valid_output",
                    ]
                success &= problem.validate_invalid_extra_data()
                success &= problem.validate_valid_extra_data()
            if action == "all" or not specified or config.args.input:
                success &= problem.validate_data(validate.Mode.INPUT)
            if action == "all" or not specified or config.args.answer:
                success &= problem.validate_data(validate.Mode.ANSWER)
            if action == "all" or not specified or config.args.valid_output:
                success &= problem.validate_data(validate.Mode.VALID_OUTPUT)
        if action in ["run", "all"]:
            success &= problem.run_submissions()
        if action in ["test"]:
            config.args.no_bar = True
            success &= problem.test_submissions()
        if action in ["constraints"]:
            success &= constraints.check_constraints(problem)
        if action in ["check_testing_tool"]:
            problem.check_testing_tool()
        if action in ["time_limit"]:
            success &= problem.determine_time_limit()
        if action in ["zip"]:
            output = problem.path / f"{problem.name}.zip"

            problem_zips.append(output)
            if not config.args.skip:
                if not config.args.no_generate:
                    # Set up arguments for generate.
                    old_args = config.args.copy()
                    config.args.check_deterministic = not config.args.force
                    config.args.add = None
                    config.args.verbose = 0
                    config.args.testcases = None
                    config.args.force = False
                    success &= generate.generate(problem)
                    config.args = old_args

                if not config.args.kattis:
                    success &= latex.build_problem_pdfs(problem)
                    if not config.args.no_solutions:
                        success &= latex.build_problem_pdfs(
                            problem, build_type=latex.PdfType.SOLUTION
                        )

                    if any(problem.path.glob(str(latex.PdfType.PROBLEM_SLIDE.path("*")))):
                        success &= latex.build_problem_pdfs(
                            problem, build_type=latex.PdfType.PROBLEM_SLIDE
                        )

                if not config.args.force:
                    success &= problem.validate_data(validate.Mode.INPUT, constraints={})
                    success &= problem.validate_data(validate.Mode.ANSWER, constraints={})

                # Write to problemname.zip, where we strip all non-alphanumeric from the
                # problem directory name.
                success &= export.build_problem_zip(problem, output)

        if len(problems) > 1:
            eprint()

    if action in ["export"]:
        languages = export.select_languages(problems)
        export.export_contest_and_problems(problems, languages)

    if level == "problemset":
        eprint(f"{Style.BRIGHT}CONTEST {contest_name}{Style.RESET_ALL}")

        # build pdf for the entire contest
        if action in ["pdf"]:
            success &= latex.build_contest_pdfs(contest_name, problems, tmpdir, web=config.args.web)

        if action in ["solutions"]:
            success &= latex.build_contest_pdfs(
                contest_name,
                problems,
                tmpdir,
                build_type=latex.PdfType.SOLUTION,
                web=config.args.web,
            )

        if action in ["problem_slides"]:
            success &= latex.build_contest_pdfs(
                contest_name,
                problems,
                tmpdir,
                build_type=latex.PdfType.PROBLEM_SLIDE,
                web=config.args.web,
            )

        if action in ["zip"]:
            languages = []
            if not config.args.kattis:
                languages = export.select_languages(problems)

                # Only build the problem slides if at least one problem has the TeX for it
                slideglob = latex.PdfType.PROBLEM_SLIDE.path("*")
                build_problem_slides = any(
                    any(problem.path.glob(str(slideglob))) for problem in problems
                )

                for language in languages:
                    success &= latex.build_contest_pdfs(contest_name, problems, tmpdir, language)
                    success &= latex.build_contest_pdfs(
                        contest_name, problems, tmpdir, language, web=True
                    )
                    if not config.args.no_solutions:
                        success &= latex.build_contest_pdf(
                            contest_name,
                            problems,
                            tmpdir,
                            language,
                            build_type=latex.PdfType.SOLUTION,
                        )
                        success &= latex.build_contest_pdf(
                            contest_name,
                            problems,
                            tmpdir,
                            language,
                            build_type=latex.PdfType.SOLUTION,
                            web=True,
                        )
                    if build_problem_slides:
                        success &= latex.build_contest_pdf(
                            contest_name,
                            problems,
                            tmpdir,
                            language,
                            build_type=latex.PdfType.PROBLEM_SLIDE,
                        )

                if not build_problem_slides:
                    log(f"No problem has {slideglob.name}, skipping problem slides")

            outfile = contest_name + ".zip"
            if config.args.kattis:
                outfile = contest_name + "-kattis.zip"
            export.build_contest_zip(problems, problem_zips, outfile, languages)

        if action in ["update_problems_yaml"]:
            export.update_problems_yaml(
                problems,
                (
                    re.split("[^#0-9A-Za-z]", config.args.colors.strip())
                    if config.args.colors
                    else None
                ),
            )

    if not success or config.n_error > 0 or config.n_warn > 0:
        sys.exit(1)


# Takes command line arguments
def main() -> None:
    def interrupt_handler(sig: Any, frame: Any) -> None:
        fatal("Running interrupted")

    signal.signal(signal.SIGINT, interrupt_handler)

    try:
        parser = build_parser()
        run_parsed_arguments(parser.parse_args())
    except AbortException:
        fatal("Running interrupted")


if __name__ == "__main__":
    main()


def test(args: list[str]) -> None:
    config.RUNNING_TEST = True

    # Make sure to cd back to the original directory before returning.
    # Needed to stay in the same directory in tests.
    original_directory = Path.cwd()
    config.n_warn = 0
    config.n_error = 0
    contest._contest_yaml = None
    contest._problems_yaml = None
    try:
        parser = build_parser()
        run_parsed_arguments(parser.parse_args(args), personal_config=False)
    finally:
        os.chdir(original_directory)
        ProgressBar.current_bar = None
