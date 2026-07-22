import contextlib
import os
import statistics
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path
from typing import Any, cast, Literal, Optional

from colorama import ansi, Fore, Style
from dateutil import parser

from bapctools import config, generate, languages, latex, validate
from bapctools.problem import Problem
from bapctools.util import drop_suffix, eprint, error, glob, log, ShellCommand


def stats(problems: list[Problem]) -> None:
    problem_stats(problems)
    if config.args.all:
        stats_all(problems)


# lists all testcases, tries to consider generators.yaml
@cache
def testcases(problem: Problem) -> set[Path]:
    with config.suppress_warnings(level=2):
        with open(os.devnull, "w") as devnull:
            with contextlib.redirect_stderr(devnull):
                gen_config = generate.GeneratorConfig(problem)
    if gen_config.n_parse_error > 0:
        return set()
    if gen_config.has_yaml:
        return {
            problem.path / "data" / p.parent / p.name
            for p, x in gen_config.known_cases.items()
            if x.ok
        }
    else:
        files = []
        for ext in (".in", ".in.download", ".in.statement", ".interaction"):
            files += [
                drop_suffix(f, [ext])
                for f in glob(problem.path, f"data/**/*{ext}")
                if not f.is_symlink()
            ]
        return set(files)


def testcase_selector(root: str | Sequence[str]) -> Callable[[Problem], int]:
    if isinstance(root, str):
        root = (root,)
    return lambda p: len([x for x in testcases(p) if x.parts[2] in root])


def _skip_path(path: Path) -> bool:
    if path.is_file():
        # Exclude files containing 'TODO: Remove'.
        try:
            data = path.read_text()
        except UnicodeDecodeError:
            return True
        if "TODO: Remove" in data:
            return True
    if path.is_dir():
        for f in glob(path, "*"):
            if f.is_file() and _skip_path(f):
                return True
    return False


@cache
def _submission_language(file: Path) -> Optional[str]:
    source_files = []
    if file.is_dir():
        source_files = list(glob(file, "*"))
    elif file.is_file():
        source_files = [file]

    candidates = []
    for lang in languages.languages():
        score, matching = lang.evaluate(source_files)
        if matching:
            candidates.append((score, lang, matching))
    return max(candidates)[1].code if candidates else None


def submission_selector(root: str, languages: str | Sequence[str]) -> Callable[[Problem], int]:
    if isinstance(languages, str):
        languages = (languages,)

    def selector(problem: Problem) -> int:
        selected = []
        for submission in problem.raw_submissions():
            language = submission.expectations.language
            if language is None:
                language = _submission_language(submission.path)
            if language is None or language not in languages:
                continue
            if submission.short_path.parts[0] != root:
                continue
            selected.append(submission.path)
        return len(selected)

    return selector


def glob_selector(globs: str | list[str]) -> Callable[[Problem], int | float]:
    if isinstance(globs, str):
        globs = [globs]

    def selector(problem: Problem) -> int | float:
        files = []
        for glob_pattern in globs:
            files += [f for f in glob(problem.path, glob_pattern) if not _skip_path(f)]
        return len(set(files))

    return selector


def comment(problem: Problem) -> str:
    verified = bool(problem.settings.verified)
    comment = problem.settings.comment or ""

    if verified:
        if not comment:
            comment = "DONE"
        comment = Fore.GREEN + comment + Style.RESET_ALL
    else:
        comment = Fore.YELLOW + comment + Style.RESET_ALL
    return comment


class Column:
    def __init__(
        self,
        name: str,
        function: Callable[[Problem], int | float | str],
        *,
        width: int = 0,
        threshold: Literal[True] | int = 0,
        upper_bound: Optional[int] = None,
        align: str = ">",
        suppress: Optional[Callable[[Problem], bool]] = None,
    ) -> None:
        self.name = name
        self.function = function
        self.width = max(len(name), width)
        self.threshold = threshold
        self.upper_bound = upper_bound
        self.align = align
        self.suppress = suppress

    def format_header(self) -> str:
        return f"{self.name:<{self.width}}"

    def get_value(self, problem: Problem) -> Optional[int | float | str]:
        if self.suppress is not None and self.suppress(problem):
            return None
        return self.function(problem)

    def format(self, value: Optional[int | float | str], plain: bool = False) -> str:
        color = ""
        msg = ""
        if value is None:
            pass
        elif isinstance(value, str):
            msg = value
        elif plain:
            msg = f"{value:.1f}" if isinstance(value, float) else str(value)
        elif self.threshold is True:
            # threshold columns are just formatted as Y or N
            if value >= 1:
                color = Fore.WHITE
                msg = "Y"
            else:
                color = Fore.RED
                msg = "N"
        else:
            # values are colored depending on threshold and upper_bound
            # threshold: a mandatory lower bound
            # upper_bound: a suggested upper bound
            color = Fore.WHITE
            if self.upper_bound is not None and value > self.upper_bound:
                color = Fore.YELLOW
            if value < self.threshold:
                color = Fore.RED
            msg = f"{value:.1f}" if isinstance(value, float) else str(value)
        return f"{color}{msg:{self.align}{self.width}}{Style.RESET_ALL}"


def problem_stats(problems: list[Problem]) -> None:
    name_width = max((len(f"{p.label} {p.name}") for p in problems), default=0)

    columns: list[Column] = [
        Column("problem", lambda p: f"{p.label} {p.name}", width=name_width, align="<"),
        Column("  time", lambda p: p.limits.time_limit),
        Column("yaml", glob_selector("problem.yaml"), threshold=True),
        Column("tex", glob_selector(str(latex.PdfType.PROBLEM.path("*"))), threshold=1),
        Column("sol", glob_selector(str(latex.PdfType.SOLUTION.path("*"))), threshold=1),
        Column(
            "  val: I", glob_selector(f"{validate.InputValidator.source_dir}/*"), threshold=True
        ),
        Column(
            "A",
            glob_selector(f"{validate.AnswerValidator.source_dir}/*"),
            threshold=True,
            suppress=lambda p: p.interactive,
        ),
        Column(
            "O",
            glob_selector(f"{validate.OutputValidator.source_dir}/*"),
            threshold=True,
            suppress=lambda p: not p.custom_output,
        ),
        Column("  sample", testcase_selector("sample"), threshold=2, upper_bound=6),
        Column("secret", testcase_selector("secret"), threshold=30, upper_bound=100),
        Column("inv", testcase_selector(config.INVALID_CASE_DIRECTORIES)),
        Column("v_o", testcase_selector("valid_output")),
        Column("   AC", glob_selector("submissions/accepted/*"), threshold=3),
        Column(" WA", glob_selector("submissions/wrong_answer/*"), threshold=2),
        Column("TLE", glob_selector("submissions/time_limit_exceeded/*"), threshold=1),
        Column("subs", glob_selector("submissions/*/*"), threshold=6),
        Column("  c(++)", submission_selector("accepted", ("c", "cpp", "cppgmp")), threshold=1),
        Column(
            "py",
            submission_selector("accepted", ("python2", "python3", "python3numpy")),
            threshold=1,
        ),
        Column("java", submission_selector("accepted", ("java", "javaalgs4")), threshold=1),
        Column("kt", submission_selector("accepted", "kotlin"), threshold=1),
        Column("   comment", comment, align="<"),
    ]

    # print header
    header = [c.format_header() for c in columns]
    header_string = " ".join(header)
    eprint(Style.BRIGHT + header_string + Style.RESET_ALL)

    total: list[int | float] = [0] * len(columns)
    # print rows
    for problem in problems:
        values = [c.get_value(problem) for c in columns]
        for i, v in enumerate(values):
            if isinstance(v, (int, float)):
                total[i] += v
        eprint(*(c.format(v) for c, v in zip(columns, values)))

    # print the cumulative count
    eprint("-" * len(header_string))
    total_row: list[Optional[int | float | str]] = list(total)
    total_row[0] = "TOTAL"
    total_row[-1] = None
    eprint(*(c.format(v, plain=True) for c, v in zip(columns, total_row)))


try:
    import pygments
    from pygments import lexers

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


@cache
def loc(file: Path) -> Optional[int]:
    if file.is_dir():
        return sum(loc(f) or 0 for f in glob(file, "*"))
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
        return count + 1 if has_code else count
    except Exception:
        # Either we could not read the file (for example binaries)
        # or we did not find a lexer
        return None


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
        "C(++)": ("c", "cpp", "cppgmp"),
        "Python": ("python2", "python3", "python3numpy"),
        "Java": ("java", "javaalgs4"),
        "Kotlin": ("kotlin"),
    }

    def get_submissions_row(
        display_name: str, codes: Optional[Sequence[str]] = None, *, team_submissions: bool
    ) -> list[str | float | int]:
        lines: list[str | float | int] = []
        values = []
        for problem in problems:
            submissions = list[Path]()
            if team_submissions:
                directory = Path.cwd() / "submissions" / problem.name / "accepted"
                for file in glob(directory, "*"):
                    if _skip_path(file):
                        continue
                    if codes is not None:
                        language = _submission_language(file)
                        if language is None or language not in codes:
                            continue
                    submissions.append(file)
            else:
                for submission in problem.raw_submissions():
                    if codes is not None:
                        language = submission.expectations.language
                        if language is None:
                            language = _submission_language(submission.path)
                        if language is None or language not in codes:
                            continue
                    if submission.short_path.parts[0] != "accepted":
                        continue
                    submissions.append(submission.path)
            cur_lines = [loc(submission) for submission in submissions]
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
    best_jury = get_submissions_row("Jury", team_submissions=False)
    eprint(format_row(*best_jury))
    for display_name, codes in languages.items():
        values = get_submissions_row(display_name, codes, team_submissions=False)
        for i in range(1, 1 + len(problems)):
            if values[i] == best_jury[i]:
                values[i] = format_value(values[i], Fore.CYAN)
        eprint(format_row(*values))

    # handle team submissions
    if Path("submissions").is_dir():
        eprint("-" * len(header))
        best_team = get_submissions_row("Teams", team_submissions=True)
        eprint(format_row(*best_team))
        for display_name, codes in languages.items():
            values = get_submissions_row(display_name, codes, team_submissions=True)
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
    cases = [len(testcases(p)) for p in problems]
    case_stats = get_stats(cases)
    eprint(format_row("Testcases", *cases, *case_stats))
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
