import shutil
import statistics
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from dateutil import parser
from pathlib import Path
from typing import Literal, Any

from colorama import ansi, Fore, Style

import config
import generate
import latex
import program
import validate
from util import error, exec_command, glob, warn

Selector = str | Callable | list[str] | list[Callable]


def stats(problems):
    problem_stats(problems)
    if config.args.more:
        more_stats(problems)


# This prints the number belonging to the count.
# This can be a red/white colored number, or Y/N
def _get_stat(count, threshold=True, upper_bound=None):
    if threshold is True:
        if count is None:
            return Fore.WHITE + " " + Style.RESET_ALL
        if count >= 1:
            return Fore.WHITE + "Y" + Style.RESET_ALL
        else:
            return Fore.RED + "N" + Style.RESET_ALL
    color = Fore.WHITE
    if upper_bound is not None and count > upper_bound:
        color = Fore.YELLOW
    if count < threshold:
        color = Fore.RED
    return color + str(count) + Style.RESET_ALL


def problem_stats(problems):
    stats: list[
        tuple[str, Selector] | tuple[str, Selector, int] | tuple[str, Selector, int, int]
    ] = [
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
        "  c(++)": ["C", "C++"],
        "py": ["Python 2", "Python 3", "CPython 2", "CPython 3"],
        "java": ["Java"],
        "kt": ["Kotlin"],
    }
    for column, lang_names in languages.items():
        paths = []
        lang_defined = False
        for lang_id, lang_definition in program.languages().items():
            if lang_definition["name"] in lang_names:
                lang_defined = True
                # dict.get() returns None if key 'files' is not declared
                lang_globs = lang_definition.get("files")
                if lang_globs:
                    paths += [f"submissions/accepted/{glob}" for glob in lang_globs.split()]
                else:
                    warn(
                        f"Language {lang_id} ('{lang_definition['name']}') "
                        "does not define `files:` in languages.yaml"
                    )
        if paths:
            stats.append((column, list(set(paths)), 1))
        if not lang_defined:
            warn(
                f"Language {column.strip()} ({str(lang_names)[1:-1]}) not defined in languages.yaml"
            )

    headers = ["problem", *(h[0] for h in stats), "   comment"]
    cumulative = [0] * (len(stats))

    header_string = ""
    format_string = ""
    for header in headers:
        if header == "problem":
            width = len(header)
            for problem in problems:
                width = max(width, len(problem.label + " " + problem.name))
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
    print(Style.BRIGHT + header + Style.RESET_ALL, file=sys.stderr)

    for problem in problems:
        generated_testcases = generate.testcases(problem)

        def count(path):
            if isinstance(path, list):
                return set.union(*(count(p) for p in path))
            if callable(path):
                return path(generated_testcases)
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

        def value(x):
            if x[0] == "  time" or x[0] == "subs":
                return x[1](problem)
            if x[0] == "A" and problem.interactive:
                return None  # Do not show an entry for the answer validator if it is not required
            if x[0] == "O" and not problem.custom_output:
                return None  # Do not show an entry for the output validator if it is not required
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

        print(
            format_string.format(
                problem.label + " " + problem.name,
                *[
                    _get_stat(
                        counts[i],
                        # mypy does not support variable-length tuples very well:
                        # https://github.com/python/mypy/pull/16237#:~:text=indirect%20comparisons
                        True if len(stats[i]) <= 2 else stats[i][2],  # type: ignore[misc]
                        None if len(stats[i]) <= 3 else stats[i][3],  # type: ignore[misc]
                    )
                    for i in range(len(stats))
                ],
                comment,
            ),
            file=sys.stderr,
        )

    # print the cumulative count
    print("-" * len(header), file=sys.stderr)
    print(
        format_string.format("TOTAL", *(_get_stat(x, False) for x in cumulative), ""),
        file=sys.stderr,
    )


try:
    import pygments
    from pygments import lexers

    loc_cache: dict[Path, int | None] = {}
    has_pygments = True
except Exception:
    has_pygments = False


def _is_code(language, type, text):
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


def loc(file):
    if file not in loc_cache:
        try:
            content = file.read_text()
            lexer = lexers.guess_lexer_for_filename(file, content)
            assert isinstance(lexer, pygments.lexer.Lexer)
            language = lexer.name.lower()
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


def more_stats(problems):
    if not has_pygments:
        error("stats --more needs pygments. Install python[3]-pygments.")
        return

    stat_name_len = 10
    stat_len = 5

    # solution stats
    columns = [p.label for p in problems] + ["sum", "min", "avg", "max"]

    def get_stats(values, missing="-"):
        if not values:
            return [missing] * 4
        return [sum(values), min(values), statistics.mean(values), max(values)]

    header_string = f"{{:<{stat_name_len}}}" + f" {{:>{stat_len}}}" * len(columns)
    format_string = (
        f"{{:<{stat_name_len + len(Fore.WHITE)}}}{Style.RESET_ALL}"
        + f" {{:>{stat_len + len(Fore.WHITE)}}}{Style.RESET_ALL}" * len(columns)
    )

    print(file=sys.stderr)
    header = header_string.format("", *columns)
    print(Style.BRIGHT + header + Style.RESET_ALL, file=sys.stderr)
    print("-" * len(header), file=sys.stderr)

    def format_row(*values):
        printable = []
        for value in values:
            if isinstance(value, float):
                value = f"{value:.1f}"
            elif isinstance(value, timedelta):
                hours = int(value.total_seconds()) // (60 * 60)
                days = int(value.total_seconds()) // (60 * 60 * 24)
                weeks = int(value.total_seconds()) // (60 * 60 * 24 * 7)
                if hours < 3 * 24:
                    value = f"{hours}h"
                elif days < 4 * 7:
                    value = f"{days}d"
                else:
                    value = f"{weeks}w"
            elif not isinstance(value, str):
                value = str(value)
            if not value.startswith(ansi.CSI):
                value = f"{Fore.WHITE}{value}"
            printable.append(value)
        return format_string.format(*printable)

    languages: dict[str, list[str] | Literal[True]] = {
        "C(++)": ["C", "C++"],
        "Python": ["Python 2", "Python 3", "CPython 2", "CPython 3"],
        "Java": ["Java"],
        "Kotlin": ["Kotlin"],
    }

    def get_submissions_row(display_name, names):
        paths = []
        if names is True:
            paths.append("submissions/accepted/*")
        else:
            assert isinstance(names, list)
            for config in program.languages().values():
                if config["name"] in names:
                    globs = config["files"].split() or []
                    paths += [f"submissions/accepted/{glob}" for glob in globs]
            paths = list(set(paths))

        lines = [display_name]
        values = []
        for problem in problems:
            files = {file for path in paths for file in glob(problem.path, path)}
            cur_lines = [loc(file) for file in files]
            cur_lines = [x for x in cur_lines if x is not None]
            if cur_lines:
                best = min(cur_lines)
                values.append(best)
                lines.append(best)
            else:
                lines.append(f"{Fore.RED}-")
        lines += get_stats(values)
        return lines

    best = get_submissions_row("Solution", True)
    print(format_row(*best), file=sys.stderr)
    for display_name, names in languages.items():
        values = get_submissions_row(display_name, names)
        for i in range(1, 1 + len(problems)):
            if values[i] == best[i]:
                values[i] = f"{Fore.CYAN}{values[i]}"
        print(format_row(*values), file=sys.stderr)

    # TODO: analyze team submissions?

    # git stats
    if shutil.which("git") is None:
        error("git command not found!")
        return

    def git(*args):
        res = exec_command(
            ["git", *args],
            crop=False,
            preexec_fn=False,
            timeout=None,
        )
        return res.out if res else ""

    if not git("rev-parse", "--is-inside-work-tree").startswith("true"):
        error("not inside git")
        return

    def parse_time(date: str):
        return parser.parse(date) if date else None

    print("-" * len(header), file=sys.stderr)
    testcases = [len(generate.testcases(p)) for p in problems]
    testcases += get_stats(testcases)
    print(format_row("Testcases", *testcases), file=sys.stderr)
    changed: list[Any] = []
    for p in problems:
        times = [
            parse_time(git("log", "--format=%cI", "-1", "--", p.path / path))
            for path in ["generators", "data"]
        ]
        times = [t for t in times if t]
        if times:
            time = max(times)
            duration = datetime.now(timezone.utc) - time
            changed.append(duration.total_seconds())
        else:
            changed.append(None)
    changed += get_stats(changed)
    changed = [timedelta(seconds=s) for s in changed]
    changed[-4] = "-"  # sum of last changed is meaningless...
    print(format_row("└─changed", *changed), file=sys.stderr)

    # this is hacky and does not handle all renames properly...
    # for example: if A is renamed to C and B is renamed to A this will break
    def countCommits(problem):
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
    commits += get_stats(commits, "-")
    commits[-4] = "-"  # one commit can change multiple problems so the sum is meaningless...
    print(format_row("Commits", *commits), file=sys.stderr)
    print(file=sys.stderr)
    print(
        f"{Fore.CYAN}Total Commits{Style.RESET_ALL}:",
        int(git("rev-list", "--all", "--count")),
        file=sys.stderr,
    )
    print(
        f"{Fore.CYAN}Total Authors{Style.RESET_ALL}:",
        git("shortlog", "--group=%ae", "-s").count("\n"),
        file=sys.stderr,
    )
    duration = datetime.now(timezone.utc) - parser.parse(
        git("log", "--reverse", "--format=%cI").partition("\n")[0]
    )
    print(
        f"{Fore.CYAN}Preparation{Style.RESET_ALL}: {duration.days}d, {duration.seconds // 3600}h",
        file=sys.stderr,
    )
