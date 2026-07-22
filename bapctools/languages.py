import os
import re
import shlex
import shutil
import string
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Optional

from bapctools import config
from bapctools.util import (
    BAR_TYPE,
    error,
    fatal,
    once,
    read_yaml,
    warn,
    YamlParser,
)


class Language:
    CODE_REGEX: Final[re.Pattern[str]] = re.compile("[a-z][a-z0-9]*")
    ENTRY_POINTS: Final[Sequence[str]] = ("binary", "mainfile", "mainclass", "Mainclass")
    VARIABLES: Final[Sequence[str]] = ("path", "files", *ENTRY_POINTS, "memlim")
    # Do not warn for the same mixing executeable multiple times.
    warn_cache: set[str] = set()

    def __init__(self, code: str, conf: dict[object, object], *, internal: bool = False) -> None:
        self.ok = True
        self.internal = internal
        self.warned_fallback = False
        parser = YamlParser("languages.yaml", conf, code)

        self.code = code
        self.name = parser.extract_and_error("name", str)
        self.priority = parser.extract_and_error("priority", int)
        self.files = parser.extract_and_error("files", str).split()
        self.shebang = None
        shebang = parser.extract_optional("shebang", str)
        if shebang is not None:
            try:
                self.shebang = re.compile(shebang)
            except re.error:
                warn(f"invalid shebang in languages.yaml for '{code}'. SKIPPED.")
        self.compile = parser.extract_optional("compile", str)
        self.run = parser.extract_and_error("run", str)

        def get_variables(command: str) -> set[str]:
            fields = []
            for _, field, format_spec, _ in string.Formatter().parse(command):
                if field is None:
                    continue
                # cannot distinguish "{path}" from "{path:}" but better than nothing...
                if format_spec:
                    warn(
                        f"found meta variable {{{field}:{format_spec}}} in languages.yaml for '{code}', did you mean {{{field}}}?"
                    )
                fields.append(field)
            return set(fields)

        # check the language specification
        variables = get_variables(self.run)
        if self.compile is not None:
            variables |= get_variables(self.compile)
        for unknown in variables - set(Language.VARIABLES):
            error(f"Unknown meta variable {unknown} in languages.yaml for '{code}'.")
            self.ok = False
        entry_points = variables & set(Language.ENTRY_POINTS)
        if len(entry_points) != 1:
            error(f"Expected exactly one entry point in languages.yaml for '{code}'.")
            self.ok = False

        def get_exe(key: str, command: str) -> Optional[str]:
            try:
                exe = shlex.split(command)[0]
                if exe and exe[0] != "{":
                    return exe
            except (IndexError, ValueError):
                error(f"invalid value for key '{key}' in languages.yaml for '{code}'")
                self.ok = False
            return None

        self.compile_exe = get_exe("compile", self.compile) if self.compile else None
        self.run_exe = get_exe("run", self.run)

        parser.check_unknown_keys()
        self.ok &= parser.errors == 0

    def __lt__(self, other: "Language") -> bool:
        return self.code > other.code

    # Returns true when file f matches the shebang regex.
    def _matches_shebang(self, f: Path) -> bool:
        if self.shebang is None:
            return True
        try:
            with f.open() as o:
                return self.shebang.search(o.readline()) is not None
        except UnicodeDecodeError:
            return False

    # Returns true when file f matches the shebang regex and the file glob.
    def _matches(self, f: Path) -> bool:
        return any(f.match(glob) for glob in self.files) and self._matches_shebang(f)

    def evaluate(self, files: list[Path]) -> tuple[tuple[int, int, int], list[Path]]:
        matching = [f for f in files if self._matches(f)]
        score = (self.priority // 1000, len(matching), self.priority)
        return (score, matching)

    def is_installed(self, bar: BAR_TYPE) -> bool:
        # Make sure we can compile programs for this language.
        if self.compile_exe is not None and shutil.which(self.compile_exe) is None:
            if self.compile_exe not in Language.warn_cache and config.args.verbose:
                Language.warn_cache.add(self.compile_exe)
                bar.debug(
                    f"Compile program {self.compile_exe} not found for language {self.name}. Falling back to lower priority languages."
                )
            return False
        # Make sure we can run programs for this language.
        if self.run_exe is not None and shutil.which(self.run_exe) is None:
            if self.run_exe not in Language.warn_cache and config.args.verbose:
                Language.warn_cache.add(self.run_exe)
                bar.debug(
                    f"Run program {self.run_exe} not found for language {self.name}. Falling back to lower priority languages."
                )
            return False
        return True

    def warn_fallback(self, bar: BAR_TYPE) -> None:
        if self.warned_fallback:
            return
        self.warned_fallback = True
        bar.debug(f"Falling back to {self.name}.")


BINARY_NAME: Final[str] = "run"
BUILD_NAME: Final[str] = "build"

BUILD: Final[Language] = Language(
    "build",
    {
        "name": "build",
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
        "name": "manual",
        "priority": 9998,
        "files": BINARY_NAME,
        "run": "{binary}",
    },
    internal=True,
)

CHECKTESTDATA: Final[Language] = Language(
    "checktestdata",
    {
        "name": "checktestdata",
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
        "name": "viva",
        "priority": 1,
        "files": "*.viva",
        "run": shlex.join(
            [
                "java",
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

SPEC_LANGUAGE_CODES: Final[Sequence[str]] = (
    "c",
    "cpp",
    "cppgmp",
    "python3",
    "python3numpy",
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
def languages() -> Sequence[Language]:
    languages_path = Path("languages.yaml")
    if languages_path.is_file():
        raw_languages = read_yaml(languages_path)
    else:
        raw_languages = read_yaml(config.RESOURCES_ROOT / "config" / "languages.yaml")
    if not isinstance(raw_languages, dict):
        fatal("could not parse languages.yaml.")

    languages = []
    priorities: dict[int, str] = {}
    for code, lang_conf in raw_languages.items():
        if not isinstance(code, str):
            error("keys in languages.yaml must be strings. SKIPPED.")
            continue
        if not Language.CODE_REGEX.match(code):
            error(f"key {code} in languages.yaml is invalid. SKIPPED.")
            continue
        if not isinstance(lang_conf, dict):
            error(f"invalid entry {code} in languages.yaml. SKIPPED.")
            continue
        lang = Language(code, lang_conf)
        if not lang.ok:
            continue

        languages.append(lang)
        if lang.priority in priorities:
            warn(
                f"'{lang.code}' and '{priorities[lang.priority]}' have the same priority in languages.yaml."
            )
        priorities[lang.priority] = lang.code

    for lang in EXTRA_LANGUAGES:
        assert lang.ok
        languages.append(lang)

    _languages = tuple(languages)
    return _languages
