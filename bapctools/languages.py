import copy
import os
import re
import shlex
import shutil
import string
import sys
from collections.abc import Mapping, Sequence, Set
from pathlib import Path
from typing import Final, Optional

from bapctools import bar, config
from bapctools.bar import PrintBar
from bapctools.util import home_config_dir, once, read_yaml, YamlParser


class TemplateCommand:
    ENTRY_POINTS: Final[Set[str]] = {"binary", "mainfile", "mainclass", "Mainclass"}
    VARIABLES: Final[Set[str]] = {"path", "files", *ENTRY_POINTS, "memlim"}
    # Do not warn for the same missing executeable multiple times.
    warn_cache: set[str] = set()

    @staticmethod
    def find_variables(command: str) -> set[str]:
        return {f for _, f, _, _ in string.Formatter().parse(command) if f is not None}

    def __init__(self, key: str, command: Optional[str]) -> None:
        self.ok = True
        self.key = key
        self.command = command

        self.exe = None
        self._exe = None

        if command is not None:
            try:
                exe = shlex.split(command)[0]
                if not TemplateCommand.find_variables(exe):
                    self._exe = exe
                    self.exe = shutil.which(exe)
            except (IndexError, ValueError):
                bar.error(f"invalid value for `{self.key}`")
                self.ok = False

    def variables(self) -> set[str]:
        return TemplateCommand.find_variables(self.command or "")

    def substitute(self, vars: Mapping[str, object]) -> list[str]:
        assert set(vars) <= TemplateCommand.VARIABLES
        ret = shlex.split((self.command or "").format(**vars))
        if self.exe is not None:
            ret[0] = self.exe
        return ret

    def is_installed(self) -> bool:
        if (
            self.exe is None
            and self._exe is not None
            and self._exe not in TemplateCommand.warn_cache
            and config.args.verbose
        ):
            TemplateCommand.warn_cache.add(self._exe)
            bar.verbose(
                f"{self.key.title()} program {self._exe} not found. Falling back to lower priority languages."
            )
        return self.exe is not None or self._exe is None


class Language:
    CODE_REGEX: Final[re.Pattern[str]] = re.compile("[a-z][a-z0-9]*")

    def __init__(self, code: str, conf: dict[object, object], *, internal: bool = False) -> None:
        self.ok = True
        self.internal = internal
        self.warned_fallback = False
        parser = YamlParser(conf, code)

        self.code = code
        self.name = parser.extract_and_error("name", str)
        self.priority = parser.extract_and_error("priority", int)
        self.files = parser.extract_and_error("files", str).split()

        if ("shebang" in parser.remaining) != ("shebang_files" in parser.remaining):
            if "shebang" in parser.remaining:
                found, missing = "shebang", "shebang_files"
            else:
                found, missing = "shebang_files", "shebang"
            parser.pop(found)
            parser.pop(missing)
            bar.warn(
                f"invalid entries for '{code}', {found} must be accompanied by {missing}. SKIPPED."
            )
        self.shebang = None
        self.shebang_files = None
        shebang = parser.extract_optional("shebang", str)
        if shebang is not None:
            try:
                self.shebang = re.compile(shebang)
                self.shebang_files = parser.extract_and_error("shebang_files", str).split()
            except re.error:
                bar.warn(f"invalid shebang for '{code}'. SKIPPED.")

        compile = parser.extract_optional("compile", str)
        self.compile = TemplateCommand(f"{code}.compile", compile)
        self.ok &= self.compile.ok

        run = parser.extract_and_error("run", str)
        self.run = TemplateCommand(f"{code}.run", run)
        self.ok &= self.run.ok

        # check the language specification
        variables = self.run.variables() | self.compile.variables()
        for unknown in variables - TemplateCommand.VARIABLES:
            bar.error(f"Unknown meta variable {unknown} for '{code}'.")
            self.ok = False
        entry_points = variables & TemplateCommand.ENTRY_POINTS
        if len(entry_points) != 1:
            bar.error(f"Expected exactly one entry point for '{code}'.")
            self.ok = False

        parser.check_unknown_keys()
        self.ok &= parser.errors == 0

    def __lt__(self, other: "Language") -> bool:
        return self.code > other.code

    # Returns true when file f matches the shebang regex.
    def _matches_shebang(self, f: Path) -> bool:
        if self.shebang is None:
            return True
        assert self.shebang_files is not None
        if not any(f.match(glob) for glob in self.shebang_files):
            return True
        try:
            with f.open() as o:
                return self.shebang.search(o.readline()) is not None
        except UnicodeDecodeError:
            return False

    # Returns true when file f matches the shebang regex and the file glob.
    def _matches_file(self, f: Path) -> bool:
        return any(f.match(glob) for glob in self.files)

    def evaluate(self, files: list[Path]) -> tuple[tuple[int, int], list[Path]]:
        source_files = [f for f in files if self._matches_file(f)]
        matches = [f for f in files if self._matches_shebang(f)]
        score = (len(matches), self.priority)
        return (score, source_files)

    def is_installed(self) -> bool:
        # Make sure we can compile/run programs for this language.
        return self.compile.is_installed() and self.run.is_installed()

    def warn_fallback(self) -> None:
        if self.warned_fallback:
            return
        self.warned_fallback = True
        bar.verbose(f"Falling back to {self.name}.")


BINARY_NAME: Final[str] = "run"
BUILD_NAME: Final[str] = "build"

BUILD: Final[Language] = Language(
    "build",
    {
        "name": "build+run",
        "priority": 9999,
        "files": BUILD_NAME,
        "compile": f"{{path}}{os.sep}{BUILD_NAME}",
        "run": "{binary}",
    },
    internal=True,
)
RUN: Final[Language] = Language(
    "run",
    {
        "name": "run",
        "priority": 9998,
        "files": BINARY_NAME,
        "run": "{binary}",
    },
    internal=True,
)

CHECKTESTDATA: Final[Language] = Language(
    "checktestdata",
    {
        "name": "Checktestdata",
        "priority": 2,
        "files": "*.ctd",
        "run": shlex.join([sys.executable, "-m", "checktestdata", "{mainfile}"]),
    },
    internal=True,
)
COMPILED_CHECKTESTDATA: Final[Language] = Language(
    "checktestdata",
    {
        "name": "checktestdata",
        "priority": 3,
        "files": "*.ctd",
        "compile": shlex.join(
            [sys.executable, "-m", "checktestdata", "-c", "{mainfile}.py", "{mainfile}"]
        ),
        "run": "pypy3 {mainfile}.py",
    },
    internal=True,
)
VIVA: Final[Language] = Language(
    "viva",
    {
        "name": "Viva",
        "priority": 1,
        "files": "*.viva",
        "run": shlex.join(
            [
                "java",
                "-XX:+UseSerialGC",
                "-XX:TieredStopAtLevel=1",
                "-XX:ActiveProcessorCount=2",
                "-Xss64m",
                "-Xms{memlim}m",
                "-Xmx{memlim}m",
                "-jar",
                str(config.RESOURCES_ROOT / "third_party" / "viva" / "viva.jar"),
                "{mainfile}",
            ]
        ),
    },
    internal=True,
)

EXTRA_LANGUAGES: Final[Sequence[Language]] = (
    BUILD,
    RUN,
    CHECKTESTDATA,
    COMPILED_CHECKTESTDATA,
    VIVA,
)

PYTHON_CODES: Final[Sequence[str]] = (
    "python3",
    "python2",
    "python3numpy",
    # all following are out of spec
    "python2shebang",
    "cpython2shebang",
    "cpython3",
    "cpython2",
)
SPEC_LANGUAGE_CODES: Final[Sequence[str]] = (
    "c",
    "cpp",
    "cppgmp",
    *PYTHON_CODES,
    BUILD.code,
    RUN.code,
)

VALIDATOR_LANGUAGE_CODES: Final[Sequence[str]] = (
    *SPEC_LANGUAGE_CODES,
    CHECKTESTDATA.code,
    COMPILED_CHECKTESTDATA.code,
    VIVA.code,
)


@once
@bar.restore
def languages() -> Sequence[Language]:
    languages_path = Path("languages.yaml")
    bar.use_globally(PrintBar(languages_path.name))
    raw_languages: dict[object, object] = {}

    def deepmerge(target: dict[object, object], overrides: dict[object, object]) -> None:
        for key, value in overrides.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                _target = target[key]
                assert isinstance(_target, dict)
                deepmerge(_target, value)
            else:
                target[key] = value

    for d in [config.RESOURCES_ROOT / "config", home_config_dir()]:
        file = d / languages_path
        if not file.is_file():
            continue
        tmp_languages = read_yaml(file, empty={})
        if not isinstance(tmp_languages, dict):
            bar.fatal(f"could not parse {file}.")
        deepmerge(raw_languages, tmp_languages)

    raw_merged = copy.deepcopy(raw_languages)
    if languages_path.is_file():
        tmp_languages = read_yaml(languages_path, empty={})
        if not isinstance(tmp_languages, dict):
            bar.fatal(f"could not parse {languages_path}.")
        deepmerge(raw_merged, tmp_languages)

    languages = []
    priorities: dict[int, str] = {}
    for code, merged in raw_merged.items():
        if not isinstance(code, str):
            bar.error("keys must be strings. SKIPPED.")
            continue
        if not Language.CODE_REGEX.match(code):
            bar.error(f"key {code} is invalid. SKIPPED.")
            continue
        if not isinstance(merged, dict):
            bar.error(f"invalid entry {code}. SKIPPED.")
            continue

        fallback = raw_languages.get(code)
        lang = Language(code, merged)
        if not lang.ok and isinstance(fallback, dict):
            # TODO: also use fallback if merged lang is not installed?
            lang = Language(code, fallback)
        if not lang.ok:
            continue

        languages.append(lang)
        if lang.priority in priorities:
            bar.warn(f"'{lang.code}' and '{priorities[lang.priority]}' have the same priority.")
        priorities[lang.priority] = lang.code

    if config.args.error:
        # not compiling ctd results in nicer error messages
        # => we prefer the not compiled language if -e is given
        p1, p2 = COMPILED_CHECKTESTDATA.priority, CHECKTESTDATA.priority
        COMPILED_CHECKTESTDATA.priority = min(p1, p2)
        CHECKTESTDATA.priority = max(p1, p2)

    for lang in EXTRA_LANGUAGES:
        assert lang.ok
        assert lang.internal
        languages.append(lang)

    return tuple(languages)
