# Global variables that are constant after the programs arguments have been parsed.

import copy
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Literal, Optional, TypeVar

from colorama import Fore, Style

import bapctools

# Randomly generated uuid4 for BAPCtools
BAPC_UUID: Final[str] = "8ee7605a-d1ce-47b3-be37-15de5acd757e"
BAPC_UUID_PREFIX: Final[int] = 8

SPEC_VERSION: Final[str] = "2025-09"

# return values
RTV_AC: Final[int] = 42
RTV_WA: Final[int] = 43

# limit in MiB for the ICPC Archive
ICPC_FILE_LIMIT: Final[int] = 100

SUBMISSION_DIRS: Final[Sequence[str]] = (
    "accepted",
    "wrong_answer",
    "time_limit_exceeded",
    "run_time_error",
)

# This ordering is shown in bt new_problem with questionary installed (intentionally non-alphabetical).
KNOWN_LICENSES: Final[Sequence[str]] = (
    "cc by-sa",
    "cc by",
    "cc0",
    "public domain",
    "educational",
    "permission",
    "unknown",
)

# When --table is set, this threshold determines the number of identical profiles needed to get flagged.
TABLE_THRESHOLD: Final[int] = 4

FILE_NAME_REGEX: Final[str] = "[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,254}"
COMPILED_FILE_NAME_REGEX: Final[re.Pattern[str]] = re.compile(FILE_NAME_REGEX)

CONSTANT_NAME_REGEX = "[a-zA-Z_][a-zA-Z0-9_]*"
COMPILED_CONSTANT_NAME_REGEX: Final[re.Pattern[str]] = re.compile(CONSTANT_NAME_REGEX)
CONSTANT_SUBSTITUTE_REGEX: Final[re.Pattern[str]] = re.compile(
    f"\\{{\\{{({CONSTANT_NAME_REGEX}|{CONSTANT_NAME_REGEX}\\.{CONSTANT_NAME_REGEX})\\}}\\}}"
)

BAPCTOOLS_SUBSTITUTE_REGEX: Final[re.Pattern[str]] = re.compile(
    f"\\{{%({CONSTANT_NAME_REGEX})%\\}}"
)


KNOWN_TESTCASE_EXTENSIONS: Final[Sequence[str]] = (
    ".in",
    ".ans",
    ".out",
)

KNOWN_VISUALIZER_EXTENSIONS: Final[Sequence[str]] = (
    ".png",
    ".jpg",
    ".svg",
    ".pdf",
)

KNOWN_SAMPLE_TESTCASE_EXTENSIONS: Final[Sequence[str]] = (
    ".in.statement",
    ".ans.statement",
    ".in.download",
    ".ans.download",
)

KNOWN_TEXT_DATA_EXTENSIONS: Final[Sequence[str]] = (
    *KNOWN_TESTCASE_EXTENSIONS,
    *KNOWN_SAMPLE_TESTCASE_EXTENSIONS,
    ".interaction",
    ".yaml",
)

KNOWN_DATA_EXTENSIONS: Final[Sequence[str]] = (
    *KNOWN_TEXT_DATA_EXTENSIONS,
    *KNOWN_VISUALIZER_EXTENSIONS,
)

INVALID_CASE_DIRECTORIES: Final[Sequence[str]] = (
    "invalid_input",
    "invalid_answer",
    "invalid_output",
)


SEED_DEPENDENCY_RETRIES: Final[int] = 10

# The directory containing all non-python resources
RESOURCES_ROOT: Final[Path] = Path(bapctools.__file__).parent / "resources"

# The directory from which BAPCtools is invoked.
current_working_directory: Final[Path] = Path.cwd().absolute()

# Add third_party/ to the $PATH for checktestdata.
os.environ["PATH"] += os.pathsep + str(RESOURCES_ROOT / "third_party")

# Below here is some global state that will be filled in main().

level: Optional[Literal["problem", "problemset"]] = None

# The number of warnings and errors encountered.
# The program will return non-zero when the number of errors is nonzero.
n_error: int = 0
n_warn: int = 0


# Set to true when running as a test.
RUNNING_TEST: bool = False
TEST_TLE_SUBMISSIONS: bool = False


class ARGS:
    def __init__(self, source: str | Path, **kwargs: Any) -> None:
        self._set = set[str]()
        self._source = source

        def warn(msg: Any) -> None:
            global n_warn
            # `config` is imported before `util`, so we cannot use a `PrintBar` or `eprint` here.
            print(f"{Fore.YELLOW}WARNING: {msg}{Style.RESET_ALL}", file=sys.stderr)
            n_warn += 1

        T = TypeVar("T")

        def normalize_arg(value: object, t: type[object]) -> object:
            if isinstance(value, str) and t is Path:
                value = Path(value)
            if isinstance(value, int) and t is float:
                value = float(value)
            if isinstance(value, bool) and t is int:
                value = bool(value)
            return value

        def get_optional_arg(key: str, t: type[T], constraint: Optional[str] = None) -> Optional[T]:
            if key in kwargs:
                value = normalize_arg(kwargs.pop(key), t)
                if value is None:
                    self._set.add(key)
                    return None
                if constraint:
                    assert isinstance(value, (float, int))
                    if not eval(f"{value} {constraint}"):
                        warn(
                            f"value for '{key}' in {source} should be {constraint} but is {value}. SKIPPED."
                        )
                        return None
                if isinstance(value, t):
                    self._set.add(key)
                    return value
                warn(f"incompatible value for key '{key}' in {source}. SKIPPED.")
            return None

        def get_list_arg(
            key: str, t: type[T], constraint: Optional[str] = None
        ) -> Optional[list[T]]:
            values = get_optional_arg(key, list)
            if values is None:
                return None
            checked = []
            for value in values:
                value = normalize_arg(value, t)
                if constraint:
                    assert isinstance(value, (float, int))
                    if not eval(f"{value} {constraint}"):
                        warn(
                            f"value for '{key}' in {source} should be {constraint} but is {value}. SKIPPED."
                        )
                        continue
                if not isinstance(value, t):
                    warn(f"incompatible value for key '{key}' in {source}. SKIPPED.")
                    continue
                checked.append(value)
            return checked

        def get_arg(key: str, default: T, constraint: Optional[str] = None) -> T:
            value = get_optional_arg(key, type(default), constraint)
            result = default if value is None else value
            return result

        setattr(self, "1", get_arg("1", False))
        self.action: Optional[str] = get_optional_arg("action", str)
        self.add: Optional[list[Path]] = get_list_arg("add", Path)
        self.all: int = get_arg("all", 0)
        self.answer: bool = get_arg("answer", False)
        self.api: Optional[str] = get_optional_arg("api", str)
        self.author: Optional[str] = get_optional_arg("author", str)
        self.check_deterministic: bool = get_arg("check_deterministic", False)
        self.clean: bool = get_arg("clean", False)
        self.colors: Optional[str] = get_optional_arg("colors", str)
        self.contest: Optional[Path] = get_optional_arg("contest", Path)
        self.contest_id: Optional[str] = get_optional_arg("contest_id", str)
        self.contestname: Optional[str] = get_optional_arg("contestname", str)
        self.cp: bool = get_arg("cp", False)
        self.defaults: bool = get_arg("defaults", False)
        self.default_solution: Optional[Path] = get_optional_arg("default_solution", Path)
        self.depth: Optional[int] = get_optional_arg("depth", int, ">= 0")
        self.directory: list[Path] = get_list_arg("directory", Path) or []
        self.error: bool = get_arg("error", False)
        self.force: bool = get_arg("force", False)
        self.force_build: bool = get_arg("force_build", False)
        self.generic: Optional[list[str]] = get_list_arg("generic", str)
        self.input: bool = get_arg("input", False)
        self.interaction: bool = get_arg("interaction", False)
        self.interactive: bool = get_arg("interactive", False)
        self.invalid: bool = get_arg("invalid", False)
        self.jobs: int = get_arg("jobs", (os.cpu_count() or 1) // 2, ">= 0")
        self.kattis: bool = get_arg("kattis", False)
        self.lang: Optional[list[str]] = get_list_arg("lang", str)
        self.latest_bt: bool = get_arg("latest_bt", False)
        self.legacy: bool = get_arg("legacy", False)
        self.local_time_multiplier: Optional[float] = get_optional_arg(
            "local_time_multiplier", float, "> 0"
        )
        self.memory: Optional[int] = get_optional_arg("legacy", int, "> 0")
        self.move_to: Optional[str] = get_optional_arg("colors", str)
        self.no_bar: bool = get_arg("no_bar", False)
        self.no_generate: bool = get_arg("no_generate", False)
        self.no_solution: bool = get_arg("no_solution", False)
        self.no_solutions: bool = get_arg("no_solutions", False)
        self.no_testcase_sanity_checks: bool = get_arg("no_testcase_sanity_checks", False)
        self.no_time_limit: bool = get_arg("no_time_limit", False)
        self.no_validators: bool = get_arg("no_validators", False)
        self.no_visualizer: bool = get_arg("no_visualizer", True, ">= 0")
        self.number: Optional[str] = get_optional_arg("number", str)
        self.open: Optional[Literal[True] | Path] = get_optional_arg("open", Path)
        self.order: Optional[str] = get_optional_arg("order", str)
        self.order_from_ccs: bool = get_arg("order_from_ccs", False)
        self.overview: bool = get_arg("overview", False)
        self.password: Optional[str] = get_optional_arg("password", str)
        self.post_freeze: bool = get_arg("post_freeze", False)
        self.problem: Optional[Path] = get_optional_arg("problem", Path)
        self.problemname: Optional[str] = get_optional_arg("problemname", str)
        self.remove: bool = get_arg("remove", False)
        self.reorder: bool = get_arg("reorder", False)
        self.samples: bool = get_arg("samples", False)
        self.sanitizer: bool = get_arg("sanitizer", False)
        self.skel: Optional[str] = get_optional_arg("skel", str)
        self.skip: bool = get_arg("skip", False)
        self.sort: bool = get_arg("sort", False)
        self.submissions: Optional[list[Path]] = get_list_arg("submissions", Path)
        self.table: bool = get_arg("table", False)
        self.testcases: Optional[list[Path]] = get_list_arg("testcases", Path)
        self.tex_command: Optional[str] = get_optional_arg("tex_command", str)
        self.time: int = get_arg("time", 600, "> 0")
        self.time_limit: Optional[float] = get_optional_arg("time_limit", float, "> 0")
        self.timeout: Optional[int] = get_optional_arg("timeout", int, "> 0")
        self.token: Optional[str] = get_optional_arg("token", str)
        self.tree: bool = get_arg("tree", False)
        self.type: Optional[str] = get_optional_arg("type", str)
        self.username: Optional[str] = get_optional_arg("username", str)
        self.valid_output: bool = get_arg("valid_output", False)
        self.verbose: int = get_arg("verbose", 0, ">= 0")
        self.watch: bool = get_arg("watch", False)
        self.web: bool = get_arg("web", False)
        self.write: bool = get_arg("write", False)

        for key in kwargs:
            print(key, type(kwargs[key]))
            warn(f"unknown key in {source}: '{key}'")

    def add_if_not_set(self, args: "ARGS") -> None:
        for key in args._set:
            if key not in self._set:
                setattr(self, key, getattr(args, key))
                self._set.add(key)

    def copy(self) -> "ARGS":
        res = copy.copy(self)
        res._set = copy.copy(res._set)
        return res


args = ARGS("config.py")
