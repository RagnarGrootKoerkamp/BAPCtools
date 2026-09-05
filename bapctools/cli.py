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
import difflib
import hashlib
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

import colorama
from colorama import Style

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

# Local imports
from bapctools import (
    cli_parser,  # include this early for autocomplete
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
    home_config_dir,
    inc_label,
    is_problem_directory,
    log,
    ProgressBar,
    read_yaml,
    remove_path,
    resolve_path_argument,
    verbose,
    warn,
    write_yaml,
)


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
    tmpdir = (Path(tempfile.gettempdir()) / ("bapctools_" + h)).resolve()
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
                    data = read_yaml(contest_yaml_path, empty={})
                    if not isinstance(data, dict):
                        error("could not parse contest.yaml.")
                    else:
                        data["order"] = "".join(p.label or p.name for p in problems)
                        write_yaml(data, contest_yaml_path)
                        log("Updated order")

    # Filter problems by submissions/test cases, if given.
    if config.level == "problemset" and (config.args.submissions or config.args.test_cases):
        submissions = config.args.submissions or []
        test_cases = config.args.test_cases or []

        def keep_problem(problem: Problem) -> bool:
            for s in submissions:
                x = resolve_path_argument(problem, s, "submissions")
                if x:
                    if x.is_relative_to(problem.path):
                        return True
            for t in test_cases:
                x = resolve_path_argument(problem, t, "data", suffixes=[".in"])
                if x:
                    if x.is_relative_to(problem.path):
                        return True
            return False

        problems = [p for p in problems if keep_problem(p)]

    return problems, tmpdir


# Check non unique uuid
def check_uuid(problems: list[Problem]) -> None:
    # 1. compare with problems in the same contest
    uuids: dict[str, Problem] = {}
    for p in problems:
        if p.settings.uuid in uuids:
            warn(f"{p.name} has the same uuid as {uuids[p.settings.uuid].name}")
        else:
            uuids[p.settings.uuid] = p

    # 2. compare remaining problems with a global state
    cache_path = home_config_dir() / "uuids"
    cache_path.mkdir(parents=True, exist_ok=True)
    for uuid, p in uuids.items():
        this_value = (p.path / "problem.yaml").resolve().as_posix()
        cache_entry = cache_path / uuid
        if cache_entry.is_file():
            cache_value = cache_entry.read_text().strip()
            if cache_value == this_value:
                continue
            if Path(cache_value).is_file():
                warn(f"{p.name} has the same uuid as {Path(cache_value).parent}")
                continue
        cache_entry.write_text(this_value)


# try to spot typos in the contest source
def check_source(problems: list[Problem]) -> None:
    # find most likely name
    names = Counter[str]()
    for p in problems:
        if len(p.settings.source) > 1:
            return  # there is a problem with multiple sources => no common source exists
        if not p.settings.source:
            continue
        names[p.settings.source[0].name] += 1
    if not names:
        return
    source_name, frequency = names.most_common(1)[0]
    if frequency * 2 <= len(problems) or frequency <= 3:
        return  # no clear majority source => no common source exists

    # find most likely url for source_name
    urls = defaultdict[str, float](float)
    for p in problems:
        if not p.settings.source:
            continue
        name = p.settings.source[0].name
        similarity = difflib.SequenceMatcher(None, source_name, name).ratio()
        if similarity < 0.8:
            return  # very different source name => no common source exists
        url = p.settings.source[0].url
        if not url:
            continue
        urls[url] += similarity
    source_url = [k for k, v in urls.items() if v == max(urls.values())][0] if urls else None

    for p in problems:
        if not p.settings.source:
            warn(f"{p.name} is likely missing source (expected: {source_name})")
            continue
        if p.settings.source[0].name != source_name:
            warn(f"{p.name} might have wrong source (expected: {source_name})")
        if not source_url:
            continue
        if p.settings.source[0].url != source_url:
            warn(f"{p.name} might have wrong source url (expected: {source_url})")


# NOTE: This is one of the few places that prints to stdout instead of stderr.
def print_sorted(problems: list[Problem]) -> None:
    for problem in problems:
        print(f"{problem.label:<2}: {problem.path}")


def split_submissions_and_test_cases(s: list[Path]) -> tuple[list[Path], list[Path]]:
    # We try to identify test cases by common directory names and common suffixes
    submissions = []
    test_cases = []
    for p in s:
        test_case_dirs = ["data", "sample", "secret", "fuzz", "testing_tool_cases"]
        if (
            any(part in test_case_dirs for part in p.parts)
            or p.suffix in config.KNOWN_DATA_EXTENSIONS
        ):
            # Strip potential suffix
            if p.suffix in config.KNOWN_DATA_EXTENSIONS:
                p = p.with_suffix("")
            test_cases.append(p)
        else:
            submissions.append(p)
    return (submissions, test_cases)


def read_personal_config(problem_dir: Optional[Path]) -> None:
    # possible config files, sorted by priority
    config_files = []
    if problem_dir:
        config_files.append(problem_dir / ".bapctools.yaml")
    config_files.append(Path.cwd() / ".bapctools.yaml")
    config_files.append(home_config_dir() / "config.yaml")

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
    check_uuid(problems)
    check_source(problems)

    # Split submissions and test cases when needed.
    if action in ["run", "fuzz", "time_limit", "check_testing_tool"]:
        if config.args.submissions:
            config.args.submissions, config.args.test_cases = split_submissions_and_test_cases(
                config.args.submissions
            )
        else:
            config.args.test_cases = []

    # Check for incompatible actions at the problem/problemset level.
    if level != "problem":
        if action == "test":
            fatal("Testing a submission only works for a single problem.")
        if action == "skel":
            fatal("Copying skel directories only works for a single problem.")

    if action != "generate" and config.args.test_cases and config.args.samples:
        fatal("--samples can not go together with an explicit list of test_cases.")

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
        if not config.args.test_cases:
            config.args.test_cases = [Path("data/secret")]

        # Paths *must* be inside data/.
        checked_paths = []
        for path in config.args.test_cases:
            if path.parts[0] != "data":
                warn(f'Path {path} does not match "data/*". Skipping.')
            else:
                checked_paths.append(path)
        config.args.test_cases = checked_paths

    # Handle one-off subcommands.
    if action == "tmp":
        if level == "problem":
            level_tmpdir = tmpdir / problems[0].name
        else:
            level_tmpdir = tmpdir

        if config.args.clean:
            log(f"Deleting {tmpdir}!")
            remove_path(level_tmpdir)
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
        with config.temporary_args():
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
            with config.temporary_args():
                config.args.jobs = (os.cpu_count() or 1) // 2
                config.args.add = None
                if config.args.verbose == 1:
                    config.args.verbose = 0
                config.args.no_visualizer = True
                success &= generate.generate(problem)
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
                    config.args.overrides,
                    config.args.valid_output,
                ]
            )
            if action == "all" or not specified or config.args.invalid:
                success &= problem.validate_data(validate.Mode.INVALID)
            if action == "all" or not specified or config.args.generic is not None:
                if not config.args.generic:
                    config.args.generic = [
                        "invalid_input",
                        "invalid_answer",
                        "invalid_output",
                        "valid_output",
                    ]
                success &= problem.validate_invalid_extra_data()
                success &= problem.validate_valid_extra_data()
                success &= problem.check_output_validator()
            if action == "all" or not specified or config.args.input:
                success &= problem.validate_data(validate.Mode.INPUT)
            if action == "all" or not specified or config.args.answer:
                success &= problem.validate_data(validate.Mode.ANSWER)
            if action == "all" or not specified or config.args.overrides:
                success &= problem.validate_overrides()
            if action == "all" or not specified or config.args.valid_output:
                success &= problem.validate_data(validate.Mode.VALID_OUTPUT)
        if action in ["run", "all"]:
            success &= problem.run_submissions()
        if action in ["test"]:
            with config.temporary_args():
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
                    with config.temporary_args():
                        config.args.check_deterministic = not config.args.force
                        config.args.add = None
                        if config.args.verbose == 1:
                            config.args.verbose = 0
                        config.args.test_cases = None
                        config.args.force = False
                        success &= generate.generate(problem)
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
    try:
        if sys.version_info < (3, 10):
            fatal("BAPCtools requires at least Python 3.10.")
        parser = cli_parser.PARSER
        if (
            len(sys.argv) >= 2
            and sys.argv[1] not in parser.known_actions
            and not sys.argv[1].startswith("-")
        ):
            action = sys.argv[1]
            closest = difflib.get_close_matches(action, parser.known_actions, n=1)
            hint = f", did you mean '{closest[0]}'?" if closest else ""
            parser.error(f"argument action: invalid choice: '{action}'{hint}")
        run_parsed_arguments(parser.parse_args())
    except (AbortException, KeyboardInterrupt):
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
    contest.contest_yaml.reset()
    contest.problems_yaml.reset()
    try:
        parser = cli_parser.PARSER
        run_parsed_arguments(parser.parse_args(args), personal_config=False)
    finally:
        os.chdir(original_directory)
        ProgressBar.current_bar = None
