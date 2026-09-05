#!/usr/bin/env python3

import argparse
import platform
from pathlib import Path
from typing import Any, Final, Optional

import argcomplete
from colorama import Fore, Style


# We set argument_default=SUPPRESS in all parsers,
# to make sure no default values (like `False` or `0`) end up in the parsed arguments object.
# If we would not do this, it would not be possible to check which keys are explicitly set from the command line.
# This check is necessary when loading the personal config file in `read_personal_config`.
class SuppressingParser(argparse.ArgumentParser):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs, argument_default=argparse.SUPPRESS)
        # this is set during _build_parser
        self.known_actions: list[str] = []


# We use our own version action to lazily determine the version
class LazyVersion(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: Optional[str] = None,
    ) -> None:
        from importlib.metadata import PackageNotFoundError, version

        from bapctools.util import is_mac, is_windows

        try:
            print("BAPCtools version", version("BAPCtools"))
        except PackageNotFoundError:
            print(
                Fore.YELLOW,
                "WARNING: unknown version! Please install BAPCtools using pip(x).",
                Style.RESET_ALL,
                sep="",
            )
            parser.exit(1)

        if not option_string or not option_string.startswith("--"):
            parser.exit()

        exit = 0
        if is_windows():
            os_name = f"Windows {platform.win32_ver()[0]}"
        elif is_mac():
            mac_version = platform.mac_ver()[0]
            os_name = f"macOS {mac_version}" if mac_version else "macOS"
        else:
            try:
                os_name = platform.freedesktop_os_release()["PRETTY_NAME"]
            except (OSError, KeyError):
                os_name = f"{platform.system()} {platform.release()}"
        print("- on", os_name)
        print("- running", platform.python_implementation(), platform.python_version())
        try:
            print("- with checktestdata", version("checktestdata"))
        except PackageNotFoundError:
            exit = 1
            print(Fore.YELLOW, "- missing checktestdata", Style.RESET_ALL, sep="")
        # TODO: print additional infos
        parser.exit(exit)


def _build_parser() -> SuppressingParser:
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
    parser.add_argument(
        "-v",
        "--version",
        nargs=0,
        action=LazyVersion,
        help="Display version information.",
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

    subparsers = parser.add_subparsers(title="actions", dest="action", required=True)

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
        "validate", parents=[global_parser], help="validate all data"
    )
    validate_parser.add_argument(
        "test_cases", nargs="*", type=Path, help="The test cases to run on."
    )
    validate_parser.add_argument("--input", "-i", action="store_true", help="Validate input.")
    validate_parser.add_argument(
        "--overrides",
        action="store_true",
        help="Validate testcase overrides for statement and download.",
    )
    validate_parser.add_argument("--answer", "-a", action="store_true", help="Validate answer.")
    validate_parser.add_argument(
        "--invalid", action="store_true", help="Check invalid files for validity."
    )
    validate_parser.add_argument(
        "--valid-output",
        action="store_true",
        help="Check files in 'data/valid_output' for validity.",
    )
    validate_parser.add_argument(
        "--generic",
        choices=["invalid_input", "invalid_answer", "invalid_output", "valid_output"],
        nargs="*",
        help="Generate generic (in)valid files based on the first three samples and validate them.",
    )

    move_or_remove_group = validate_parser.add_mutually_exclusive_group()
    move_or_remove_group.add_argument(
        "--remove", action="store_true", help="Remove failing test cases."
    )
    move_or_remove_group.add_argument(
        "--move-to", help="Move failing test cases to this directory."
    )

    validate_parser.add_argument(
        "--no-test-case-sanity-checks",
        action="store_true",
        help="Skip sanity checks on test cases.",
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

    # Generate Test cases
    genparser = subparsers.add_parser(
        "generate",
        parents=[global_parser],
        help="Generate test cases according to .gen files.",
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
        "test_cases",
        nargs="*",
        type=Path,
        help="The test cases to generate, given as directory, .in/.ans file, or base name.",
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
        "--no-test-case-sanity-checks",
        default=False,
        action="store_true",
        help="Skip sanity checks on test cases.",
    )

    # Fuzzer
    fuzzparser = subparsers.add_parser(
        "fuzz",
        parents=[global_parser],
        help="Generate random test cases and search for inconsistencies in AC submissions.",
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
        help="optionally supply a list of programs and test cases to run",
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
        help="Run all test cases. Use this flag twice (`-aa`) to continue even after timeouts.",
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
        help="Print a submissions x test cases table for analysis.",
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
        "--no-test-case-sanity-checks",
        action="store_true",
        help="Skip sanity checks on test cases.",
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
        help="optionally supply a list of programs and test cases on which the time limit should be based.",
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
        "test_cases",
        nargs="*",
        default=[],
        type=Path,
        help="Optionally a list of test cases to run on.",
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
        help="optionally supply a list of programs and test cases to run",
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
        help="Run all test cases and don't stop on error.",
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
        "--no-test-case-sanity-checks",
        action="store_true",
        help="Skip sanity checks on test-cases.",
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

    argcomplete.autocomplete(parser)

    if hasattr(parser, "suggest_on_error"):
        parser.suggest_on_error = True

    parser.known_actions = list(subparsers.choices.keys())
    return parser


PARSER: Final[SuppressingParser] = _build_parser()
del _build_parser
