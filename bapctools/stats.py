import statistics
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast, Literal, Optional

from colorama import ansi, Fore, Style
from dateutil import parser

from bapctools import config, generate, latex, program, validate
from bapctools.problem import Problem
from bapctools.util import eprint, error, glob, log, ShellCommand, warn

Selector = (
    str | Callable[[Problem], int | float] | list[str] | list[Callable[[set[Path]], set[str]]]
)
Stat = tuple[str, Selector] | tuple[str, Selector, int] | tuple[str, Selector, int, int]


def stats(problems: list[Problem]) -> None:
    problem_stats(problems)
    if config.args.all:
        stats_all(problems)


# This prints the number belonging to the count.
# This can be a red/white colored number, or Y/N
def _get_stat(
    count: Optional[int | float],
    threshold: Literal[True] | int = True,
    upper_bound: Optional[int] = None,
) -> str:
    if threshold is True:
        if count is None:
            return Fore.WHITE + " " + Style.RESET_ALL
        if count >= 1:
            return Fore.WHITE + "Y" + Style.RESET_ALL
        else:
            return Fore.RED + "N" + Style.RESET_ALL
    color = Fore.WHITE
    assert count is not None
    if upper_bound is not None and count > upper_bound:
        color = Fore.YELLOW
    if count < threshold:
        color = Fore.RED
    count_str = f"{count:.1f}" if isinstance(count, float) else str(count)
    return f"{color}{count_str}{Style.RESET_ALL}"


def problem_stats(problems: list[Problem]) -> None:
    stats: list[Stat] = [
        # Roughly in order of importance
        ("  time", lambda p: p.limits.time_limit, 0),
        ("yaml", "problem.yaml"),
        ("tex", str(latex.PdfType.PROBLEM.path("*")), 1),
        ("sol", str(latex.PdfType.SOLUTION.path("*")), 1),
        ("  val: I", [f"{validate.InputValidator.source_dir}/*"]),
        ("A", [f"{validate.AnswerValidator.source_dir}/*"]),
        ("O", [f"{validate.OutputValidator.source_dir}/*"]),
        (
            "  sample",
            [lambda s: {x.stem for x in s if x.parts[2] == "sample"}],
            2,
            6,
        ),
        (
            "secret",
            [lambda s: {x.stem for x in s if x.parts[2] == "secret"}],
            30,
            100,
        ),
        (
            "inv",
            [lambda s: {x.stem for x in s if x.parts[2] in config.INVALID_CASE_DIRECTORIES}],
            0,
        ),
        (
            "v_o",
            [lambda s: {x.stem for x in s if x.parts[2] in ["valid_output"]}],
            0,
        ),
        ("   AC", "submissions/accepted/*", 3),
        (" WA", "submissions/wrong_answer/*", 2),
        ("TLE", "submissions/time_limit_exceeded/*", 1),
        ("subs", lambda p: len(glob(p.path, "submissions/*/*")), 6),
    ]
    languages = {
        "  c(++)": ["c", "c++"],
        "py": ["python 2", "python 3", "cpython 2", "cpython 3"],
        "java": ["java"],
        "kt": ["kotlin"],
    }
    for column, lang_names in languages.items():
        paths = []
        lang_defined = False
        for lang in program.languages():
            if lang.name.lower() in lang_names:
                lang_defined = True
                lang_globs = lang.files
                if lang_globs:
                    paths += [f"submissions/accepted/{glob}" for glob in lang_globs]
                else:
                    warn(
                        f"Language {lang.id} ('{lang.name}') does not define `files:` in languages.yaml"
                    )
        if paths:
            stats.append((column, list(set(paths)), 1))
        if not lang_defined:
            warn(
                f"Language {column.strip()} ({str(lang_names)[1:-1]}) not defined in languages.yaml"
            )

    headers = ["problem", *(h[0] for h in stats), "   comment"]
    cumulative: list[int | float] = [0] * (len(stats))

    header_string = ""
    format_string = ""
    for header in headers:
        if header == "problem":
            width = len(header)
            for problem in problems:
                width = max(width, len(f"{problem.label} {problem.name}"))
            header_string += "{:<" + str(width) + "}"
            format_string += "{:<" + str(width) + "}"
        elif header == "  comment":
            header_string += "{}"
            format_string += "{}"
        else:
            width = len(header)
            header_string += " {:>" + str(width) + "}"
            format_string += " {:>" + str(width + len(Fore.WHITE) + len(Style.RESET_ALL)) + "}"

    header = header_string.format(*headers)
    eprint(Style.BRIGHT + header + Style.RESET_ALL)

    for problem in problems:
        generated_testcases = generate.testcases(problem)

        def count(
            path: str
            | list[str]
            | list[Callable[[set[Path]], set[str]]]
            | Callable[[set[Path]], set[str]],
        ) -> set[Any]:
            if isinstance(path, list):
                return set.union(*(count(p) for p in path))
            if callable(path):
                testcases = path(generated_testcases)
                assert isinstance(testcases, set)
                return testcases
            results: set[str | Path] = set()
            for p in glob(problem.path, path):
                if p.is_file():
                    # Exclude files containing 'TODO: Remove'.
                    try:
                        data = p.read_text()
                    except UnicodeDecodeError:
                        continue
                    if "TODO: Remove" in data:
                        continue
                    results.add(p.stem)

                if p.is_dir():
                    ok = True
                    for f in glob(p, "*"):
                        # Exclude files containing 'TODO: Remove'.
                        if f.is_file():
                            try:
                                data = f.read_text()
                                if data.find("TODO: Remove") != -1:
                                    ok = False
                                    break
                            except UnicodeDecodeError:
                                ok = False
                                pass
                    if ok:
                        results.add(p)

            return results

        def value(x: Stat) -> Optional[int | float]:
            if x[0] == "  time" or x[0] == "subs":
                assert callable(x[1])
                return x[1](problem)
            if x[0] == "A" and problem.interactive:
                return None  # Do not show an entry for the answer validator if it is not required
            if x[0] == "O" and not problem.custom_output:
                return None  # Do not show an entry for the output validator if it is not required
            assert not callable(x[1])
            return len(count(x[1]))

        counts = [value(s) for s in stats]
        for i in range(0, len(stats)):
            cumulative[i] += counts[i] or 0

        verified = bool(problem.settings.verified)
        comment = problem.settings.comment or ""

        if verified:
            if not comment:
                comment = "DONE"
            comment = Fore.GREEN + comment + Style.RESET_ALL
        else:
            comment = Fore.YELLOW + comment + Style.RESET_ALL

        eprint(
            format_string.format(
                f"{problem.label} {problem.name}",
                *[
                    _get_stat(
                        counts[i],
                        True if len(stat) <= 2 else stat[2],
                        None if len(stat) <= 3 else stat[3],
                    )
                    for i, stat in enumerate(stats)
                ],
                comment,
            ),
        )

    # print the cumulative count
    eprint("-" * len(header))
    eprint(format_string.format("TOTAL", *(_get_stat(x, False) for x in cumulative), ""))


try:
    import pygments
    from pygments import lexers

    loc_cache: dict[Path, int | None] = {}
    has_pygments = True
except Exception:
    has_pygments = False


def _is_code(language: str, type: Any, text: str) -> bool:
    if type in pygments.token.Comment and type not in (
        pygments.token.Comment.Preproc,  # pygments treats preprocessor statements as comments
        pygments.token.Comment.PreprocFile,
    ):
        return False
    if type in pygments.token.String:
        return False
    if text.rstrip(" \f\n\r\t(),:;[]{}") == "":
        return False
    # ignore some language specific keywords
    text = text.strip()
    if language == "python":
        return text != "pass"
    elif language == "batchfile":
        return text != "@"
    elif language == "sql" and text == "pass":
        return text not in ["begin", "end"]
    else:
        return True


def loc(file: Path) -> Optional[int]:
    if file not in loc_cache:
        try:
            content = file.read_text()
            lexer = lexers.guess_lexer_for_filename(file, content)
            assert isinstance(lexer, pygments.lexer.Lexer)
            language = getattr(lexer, "name").lower()
            tokens = lexer.get_tokens(content)

            count = 0
            has_code = False
            for type, text in tokens:
                for line in text.splitlines(True):
                    if _is_code(language, type, line):
                        has_code = True
                    if line.endswith("\n") and has_code:
                        count += 1
                        has_code = False
            if has_code:
                count += 1

            loc_cache[file] = count
        except Exception:
            # Either we could not read the file (for example binaries)
            # or we did not find a lexer
            loc_cache[file] = None
    return loc_cache[file]


def stats_all(problems: list[Problem]) -> None:
    if not has_pygments:
        error("stats --all needs pygments. Install python[3]-pygments.")
        return

    if not Path("submissions").is_dir():
        eprint()
        log(
            "No team submissions found, try running 'bt download_submissions' to get stats for team submissions."
        )

    stat_name_len = 10
    stat_len = 5

    # solution stats
    columns = [p.label for p in problems] + ["sum", "min", "avg", "max"]

    def get_stats(values: Sequence[float | int]) -> list[Optional[float | int]]:
        if not values:
            return [None] * 4
        return [sum(values), min(values), statistics.mean(values), max(values)]

    header_string = f"{{:<{stat_name_len}}}" + f" {{:>{stat_len}}}" * len(columns)
    format_string = (
        f"{{:<{stat_name_len + len(Fore.WHITE)}}}{Style.RESET_ALL}"
        + f" {{:>{stat_len + len(Fore.WHITE)}}}{Style.RESET_ALL}" * len(columns)
    )

    eprint()
    header = header_string.format("", *columns)
    eprint(Style.BRIGHT + header + Style.RESET_ALL)
    eprint("-" * len(header))

    def format_value(
        value: Optional[str | float | int | timedelta], default_color: str = Fore.WHITE
    ) -> str:
        if value is None:
            str_value = "-"
        elif isinstance(value, float):
            str_value = f"{value:.1f}"
        elif isinstance(value, timedelta):
            hours = int(value.total_seconds()) // (60 * 60)
            days = int(value.total_seconds()) // (60 * 60 * 24)
            weeks = int(value.total_seconds()) // (60 * 60 * 24 * 7)
            if hours < 3 * 24:
                str_value = f"{hours}h"
            elif days < 4 * 7:
                str_value = f"{days}d"
            else:
                str_value = f"{weeks}w"
        else:
            str_value = str(value)
        return str_value if str_value.startswith(ansi.CSI) else f"{default_color}{str_value}"

    def format_row(*values: Optional[str | float | int | timedelta]) -> str:
        return format_string.format(*[format_value(value) for value in values])

    languages = {
        "C(++)": ["c", "c++"],
        "Python": ["python 2", "python 3", "cpython 2", "cpython 3"],
        "Java": ["java"],
        "Kotlin": ["kotlin"],
    }

    def get_submissions_row(
        display_name: str, names: bool | list[str], team_submissions: bool
    ) -> list[str | float | int]:
        paths = []
        if names is True:
            paths.append("accepted/*")
        else:
            assert isinstance(names, list)
            for config in program.languages():
                if config.name.lower() in names:
                    globs = config.files
                    paths += [f"accepted/{glob}" for glob in globs]
            paths = list(set(paths))

        lines: list[str | float | int] = []
        values = []
        for problem in problems:
            directory = (
                Path.cwd() / "submissions" / problem.name
                if team_submissions
                else problem.path / "submissions"
            )
            files = {file for path in paths for file in glob(directory, path)}
            cur_lines = [loc(file) for file in files]
            cur_lines_filtered = [x for x in cur_lines if x is not None]
            if cur_lines_filtered:
                best = min(cur_lines_filtered)
                values.append(best)
                lines.append(best)
            else:
                lines.append("-" if team_submissions else f"{Fore.RED}-")
        if len(lines) == len(values):
            stats = [format_value(value) for value in get_stats(values)]
        else:
            color = Fore.YELLOW if team_submissions else Fore.RED
            stats = [format_value(value, color) for value in get_stats(values)]
        return [display_name, *lines, *stats]

    # handle jury solutions
    best_jury = get_submissions_row("Jury", True, False)
    eprint(format_row(*best_jury))
    for display_name, names in languages.items():
        values = get_submissions_row(display_name, names, False)
        for i in range(1, 1 + len(problems)):
            if values[i] == best_jury[i]:
                values[i] = format_value(values[i], Fore.CYAN)
        eprint(format_row(*values))

    # handle team submissions
    if Path("submissions").is_dir():
        eprint("-" * len(header))
        best_team = get_submissions_row("Teams", True, True)
        eprint(format_row(*best_team))
        for display_name, names in languages.items():
            values = get_submissions_row(display_name, names, True)
            for i in range(1, 1 + len(problems)):
                leq_jury = False
                if not isinstance(best_jury[i], (int, float)):
                    leq_jury = True
                elif isinstance(values[i], (int, float)):
                    if cast(int | float, values[i]) <= cast(int | float, best_jury[i]):
                        leq_jury = True
                if values[i] == best_team[i] and leq_jury:
                    values[i] = format_value(values[i], Fore.CYAN)
            eprint(format_row(*values))

    # git stats
    git = ShellCommand.get("git")
    if git is None:
        error("git command not found!")
        return

    if not git("rev-parse", "--is-inside-work-tree").startswith("true"):
        error("not inside git")
        return

    def parse_time(date: str) -> Optional[datetime]:
        return parser.parse(date) if date else None

    eprint("-" * len(header))
    testcases = [len(generate.testcases(p)) for p in problems]
    testcase_stats = get_stats(testcases)
    eprint(format_row("Testcases", *testcases, *testcase_stats))
    changed: list[Optional[float | int]] = []
    for p in problems:
        times = [
            parse_time(git("log", "--format=%cI", "-1", "--", p.path / path))
            for path in ["generators", "data"]
        ]
        valid_times = [t for t in times if t]
        if valid_times:
            time = max(valid_times)
            duration = datetime.now(timezone.utc) - time
            changed.append(duration.total_seconds())
        else:
            changed.append(None)
    changed += get_stats([c for c in changed if c is not None])
    changed[-4] = None  # sum of last changed is meaningless...
    changed_times = [timedelta(seconds=s) if s is not None else None for s in changed]
    eprint(format_row("└╴changed", *changed_times))

    # this is hacky and does not handle all renames properly...
    # for example: if A is renamed to C and B is renamed to A this will break
    def countCommits(problem: Problem) -> int:
        yaml_path = problem.path / "problem.yaml"
        paths = git(
            "log",
            "--all",
            "--follow",
            "--name-only",
            "--relative",
            "--format=",
            "--",
            yaml_path,
        ).split("\n")
        names = {Path(p).parent for p in paths if p.strip() != ""}
        return int(git("rev-list", "--all", "--count", "--", *names))

    commits = [countCommits(p) for p in problems]
    commit_stats = get_stats(commits)
    commit_stats[-4] = None  # one commit can change multiple problems so the sum is meaningless...
    eprint(format_row("Commits", *commits, *commit_stats))
    eprint()
    eprint(
        f"{Fore.CYAN}Total Commits{Style.RESET_ALL}:",
        int(git("rev-list", "--all", "--count")),
    )
    eprint(
        f"{Fore.CYAN}Total Authors{Style.RESET_ALL}:",
        git("shortlog", "--group=%ae", "-s").count("\n"),
    )
    duration = datetime.now(timezone.utc) - parser.parse(
        git("log", "--reverse", "--format=%cI").partition("\n")[0]
    )
    eprint(
        f"{Fore.CYAN}Preparation{Style.RESET_ALL}: {duration.days}d, {duration.seconds // 3600}h"
    )
