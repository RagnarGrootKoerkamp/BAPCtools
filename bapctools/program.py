import re
import shlex
import shutil
import stat
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Optional, TYPE_CHECKING

from colorama import Fore

from bapctools import config
from bapctools.util import (
    combine_hashes,
    copy_and_substitute,
    ensure_symlink,
    error,
    exec_command,
    ExecResult,
    ExecStatus,
    fatal,
    glob,
    has_substitute,
    hash_file,
    ProgressBar,
    read_yaml,
    strip_newline,
    warn,
    write_yaml,
    YamlParser,
)

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools.problem import Problem


class Language:
    def __init__(self, lang_id: str, conf: dict[object, object]) -> None:
        self.ok = False
        parser = YamlParser("languages.yaml", conf, lang_id)

        self.id = lang_id
        self.name = parser.extract_and_error("name", str)
        self.priority = parser.extract_and_error("priority", int)
        self.files = (parser.extract_optional("files", str) or "").split()
        self.shebang = None
        shebang = parser.extract_optional("shebang", str)
        if shebang is not None:
            try:
                self.shebang = re.compile(shebang)
            except re.error:
                warn(f"invalid shebang in languages.yaml for '{lang_id}'. SKIPPED.")
        self.compile = parser.extract_optional("compile", str)
        self.run = parser.extract_and_error("run", str)

        def get_exe(key: str, command: str) -> Optional[str]:
            try:
                exe = shlex.split(command)[0]
                if exe and exe[0] != "{":
                    return exe
            except (IndexError, ValueError):
                error(f"invalid value for key '{key}' in languages.yaml for '{lang_id}'")
                self.ok = False
            return None

        self.compile_exe = get_exe("compile", self.compile) if self.compile else None
        self.run_exe = get_exe("run", self.run)

        parser.check_unknown_keys()
        self.ok = parser.errors == 0

    def __lt__(self, other: "Language") -> bool:
        return self.id > other.id

    # Returns true when file f matches the shebang regex.
    def matches_shebang(self, f: Path) -> bool:
        if self.shebang is None:
            return True
        try:
            with f.open() as o:
                return self.shebang.search(o.readline()) is not None
        except UnicodeDecodeError:
            return False


CHECKTESTDATA: Final[Language] = Language(
    "BAPCtools:checktestdata",
    {
        "name": "Checktestdata",
        "priority": 1,
        "files": "*.ctd",
        "run": "checktestdata {mainfile}",
    },
)
VIVA: Final[Language] = Language(
    "BAPCtools:viva",
    {
        "name": "Viva",
        "priority": 2,
        "files": "*.viva",
        "run": "java -jar {viva_jar} {mainfile}",
    },
)
EXTRA_LANGUAGES: Final[Sequence[Language]] = (
    CHECKTESTDATA,
    VIVA,
    Language(
        "BAPCtools:manual",
        {
            "name": "manual",
            "priority": 9999,
            "files": "build run",
            "compile": "{build}",
            "run": "{run}",
        },
    ),
)

# The cached languages.yaml for the current contest.
_languages: Optional[Sequence[Language]] = None
_program_config_lock = threading.Lock()


def languages() -> Sequence[Language]:
    global _languages, _program_config_lock
    with _program_config_lock:
        if _languages is not None:
            return _languages

        languages_path = Path("languages.yaml")
        if languages_path.is_file():
            raw_languages = read_yaml(languages_path)
        else:
            raw_languages = read_yaml(config.RESOURCES_ROOT / "config/languages.yaml")
        if not isinstance(raw_languages, dict):
            fatal("could not parse languages.yaml.")

        languages = []
        priorities: dict[int, str] = {}
        for lang_id, lang_conf in raw_languages.items():
            if not isinstance(lang_id, str):
                error("keys in languages.yaml must be strings.")
                continue
            if not isinstance(lang_conf, dict):
                error(f"invalid entry {lang_id} in languages.yaml.")
                continue
            lang = Language(lang_id, lang_conf)
            if not lang.ok:
                continue

            languages.append(lang)
            if lang.priority in priorities:
                warn(
                    f"'{lang.id}' and '{priorities[lang.priority]}' have the same priority in languages.yaml."
                )
            priorities[lang.priority] = lang.id

        for lang in EXTRA_LANGUAGES:
            assert lang.ok
            languages.append(lang)

        _languages = tuple(languages)
        return _languages


SANITIZER_FLAGS: Final[Mapping[str, Mapping[str, str]]] = {
    "c++": {"compile": "-fsanitize=undefined,address"},
}


# A Program is class that wraps a program (file/directory) on disk. A program is usually one of:
# - a submission
# - a validator
# - a generator
# - a visualizer
#
# Constructor parameters:
# - problem: The Problem to which this Program belongs
# - path: main source file/directory: an absolute or relative path ('problem/generators/gen.py')
# - subdir: the subdirectory in which this Program belongs ('generators', 'submissions', ...)
# - deps (optional): a list of dependencies (must be Path objects)
#
# Member variables are:
# - short_path:     the path relative to problem/subdir/, or None
# - tmpdir:         the build directory in tmpfs. This is only created when build() is called.
# - input_files:    list of source files linked/copied into tmpdir
# - language:       the detected language
# - env:            the environment variables used for compile/run command substitution
# - hash:           a hash of all of the program including all source files
# - limits          a dict of the optional limts, keys are:
#                   - code
#                   - compilation_time
#                   - compilation_memory
#                   - timeout
#                   - memory
#
# After build() has been called, the following are available:
# - run_command:    command to be executed. E.g. ['/path/to/run'] or ['python3', '/path/to/main.py']. `None` if something failed.
#
# build() will return the true if building was successfull.
class Program:
    def __init__(
        self,
        problem: "Problem",
        path: Path,
        subdir: str,
        deps: Optional[list[Path]] = None,
        *,
        skip_double_build_warning: bool = False,
        limits: dict[str, int] = {},
        substitute_constants: bool = False,
    ) -> None:
        if deps is not None:
            assert isinstance(self, Generator)
            assert isinstance(deps, list)
            assert len(deps) > 0

        assert self.__class__ is not Program  # Program is abstract and may not be instantiated

        # read and parse languages.yaml
        languages()

        # Make sure we never try to build the same program twice. That'd be stupid.
        if not skip_double_build_warning:
            if path in problem._programs:
                error(f"Why would you build {path} twice?")
                assert path not in problem._programs
            problem._programs[path] = self

        self.problem = problem
        self.path = path
        self.subdir = subdir

        # Set self.name and self.tmpdir.
        # Ideally they are the same as the path inside the problem, but fallback to just the name.
        relpath = Path(path.name)
        if path.absolute().parent != problem.path.absolute():
            try:
                relpath = path.absolute().relative_to(problem.path.absolute() / subdir)
            except ValueError:
                pass

        self.short_path = relpath
        self.name: str = str(relpath)
        self.tmpdir = problem.tmpdir / self.subdir / self.name

        self.compile_command: Optional[Sequence[str | Path]] = None
        self.run_command: Optional[Sequence[str | Path]] = None
        self.hash: Optional[str] = None
        self.env: dict[str, int | str | Path] = {}
        self.limits: dict[str, int] = limits
        self.substitute_constants: bool = substitute_constants

        self.ok = True
        self.built = False

        # Detect language, dependencies, and main file
        if deps:
            self.source_files = deps
            self.has_deps = True
        else:
            if path.is_dir():
                self.source_files = list(glob(path, "*"))
                # Filter out __pycache__ files.
                self.source_files = list(
                    filter(lambda f: f.name != "__pycache__", self.source_files)
                )
            elif path.is_file():
                self.source_files = [path]
            else:
                self.source_files = []
            self.has_deps = False

        self.input_files: list[Path]  # Populated in Program.build
        self.language: Language  # Populated in Program.build

    # is file at path executable
    @staticmethod
    def _is_executable(path: Path) -> bool:
        return path.is_file() and bool(
            path.stat().st_mode & (stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        )

    # Do not warn for the same fallback language multiple times.
    warn_cache: set[str] = set()

    # Sets self.language and self.env['mainfile']
    def _get_language(self, bar: ProgressBar) -> bool:
        fallback = False
        candidates = []
        for lang in languages():
            matching_files = []
            for f in self.input_files:
                if any(f.match(glob) for glob in lang.files) and lang.matches_shebang(f):
                    matching_files.append(f)

            if len(matching_files) == 0:
                continue

            candidates.append(
                ((lang.priority // 1000, len(matching_files), lang.priority), lang, matching_files)
            )
        candidates.sort(reverse=True)

        for _, lang, files in candidates:
            name = lang.name
            # Make sure we can compile programs for this language.
            if lang.compile_exe is not None and shutil.which(lang.compile_exe) is None:
                fallback = True
                if lang.compile_exe not in Program.warn_cache and config.args.verbose:
                    Program.warn_cache.add(lang.compile_exe)
                    bar.debug(
                        f"Compile program {lang.compile_exe} not found for language {name}. Falling back to lower priority languages."
                    )
                continue
            # Make sure we can run programs for this language.
            if lang.run_exe is not None and shutil.which(lang.run_exe) is None:
                fallback = True
                if lang.run_exe not in Program.warn_cache and config.args.verbose:
                    Program.warn_cache.add(lang.run_exe)
                    bar.debug(
                        f"Run program {lang.run_exe} not found for language {name}. Falling back to lower priority languages."
                    )
                continue

            if fallback:
                if lang.id not in Program.warn_cache and config.args.verbose:
                    Program.warn_cache.add(lang.id)
                    bar.debug(f"Falling back to {name}.")

            if len(files) == 0:
                self.ok = False
                bar.error(f"No file detected for language {name} at {self.path}.")
                return False

            self.language = lang
            mainfile = None
            if not self.has_deps:
                if len(files) == 1:
                    mainfile = files[0]
                else:
                    for f in files:
                        if f.name.lower().startswith("main"):
                            mainfile = f
                    mainfile = mainfile or sorted(files)[0]
            else:
                mainfile = self.tmpdir / self.source_files[0].name

            mainclass = str(mainfile.with_suffix("").name)
            self.env = {
                "path": str(self.tmpdir),
                # NOTE: This only contains files matching the winning language.
                "files": " ".join(str(f) for f in files),
                "binary": self.tmpdir / "run",
                "mainfile": str(mainfile),
                "mainclass": mainclass,
                "Mainclass": mainclass[0].upper() + mainclass[1:],
                # Memory limit in MB.
                "memlim": self.limits.get("memory", 2048),
                # Out-of-spec variables used by 'manual' and 'Viva' languages.
                "build": (
                    self.tmpdir / "build" if (self.tmpdir / "build") in self.input_files else ""
                ),
                "run": self.tmpdir / "run",
                "viva_jar": config.RESOURCES_ROOT / "third_party/viva/viva.jar",
            }

            return True

        # The for loop did not find a suitable language.
        self.ok = False
        bar.error(f"No language detected for {self.path}.")
        return False

    def _checks(self, bar: ProgressBar) -> None:
        for f in self.source_files:
            if f.stat().st_size >= config.ICPC_FILE_LIMIT * 1024**2:
                bar.warn(
                    f"{f} is too large for the ICPC Archive (limit {config.ICPC_FILE_LIMIT}MiB)!"
                )

        # Make sure C++ does not depend on stdc++.h, because it's not portable.
        if "c++" in self.language.name.lower():
            for f in self.source_files:
                try:
                    if f.read_text().find("bits/stdc++.h") != -1:
                        if f.is_relative_to(self.problem.path / "submissions"):
                            bar.log("Should not depend on bits/stdc++.h")
                        else:
                            bar.error("Must not depend on bits/stdc++.h.", resume=True)
                        break
                except UnicodeDecodeError:
                    pass

        # Warn for known bad (non-deterministic) patterns in generators
        from bapctools.validate import Validator

        if isinstance(self, Generator) or isinstance(self, Validator):
            if "c++" in self.language.name.lower():
                for f in self.source_files:
                    try:
                        text = f.read_text()
                        bad_random = set()
                        for s in [
                            "rand\\(\\)",
                            "uniform_int_distribution",
                            "uniform_real_distribution",
                            "normal_distribution",
                            "exponential_distribution",
                            "geometric_distribution",
                            "binomial_distribution",
                            "random_device",
                            "default_random_engine",
                        ]:
                            for line in text.splitlines():
                                if s in line and "bt ignore" not in line:
                                    bad_random.add(s)
                        if bad_random:
                            bad_message = ", ".join(bad_random)
                            bar.warn(
                                f"Calling {bad_message} in {f.name} is implementation dependent in C++. Use <validation.h> instead, or add `// bt ignore` to the line."
                            )
                        if text.find("typeid(") != -1:
                            bar.warn(
                                f"Calling typeid() in {f.name} is implementation dependent in C++."
                            )
                    except UnicodeDecodeError:
                        pass
            if "python" in self.language.name.lower():
                for f in self.source_files:
                    try:
                        text = f.read_text()
                        for s in ["list(set("]:
                            if text.find(s) != -1:
                                bar.warn(
                                    "The order of sets is not fixed across implementations. Please sort the list!"
                                )
                    except UnicodeDecodeError:
                        pass

    # Return True on success.
    def _compile(self, bar: ProgressBar) -> bool:
        meta_path = self.tmpdir / "meta_.yaml"

        # Remove all non-source files.
        for f in self.tmpdir.glob("*"):
            if f not in (self.input_files + [meta_path]):
                if f.is_dir() and not f.is_symlink():
                    shutil.rmtree(f)
                else:
                    f.unlink()

        # The case where compile_command='{build}' will result in an empty list here.
        if not self.compile_command:
            return True

        try:
            ret = exec_command(
                self.compile_command,
                stdout=subprocess.PIPE,
                cwd=self.tmpdir,
                # Compile errors are never cropped.
                crop=False,
                timeout=self.limits.get("compilation_time", None),
                memory=self.limits.get("compilation_memory", None),
            )
        except FileNotFoundError as err:
            self.ok = False
            bar.error("Failed", str(err))
            return False

        if not ret.status:
            data = ""
            if ret.err is not None:
                data += strip_newline(ret.err) + "\n"
            if ret.out is not None:
                data += strip_newline(ret.out) + "\n"
            self.ok = False
            bar.error("Failed", data)
            return False

        write_yaml({"hash": self.hash, "command": self.compile_command}, meta_path)
        return True

    # Return True on success, False on failure.
    def build(self, bar: ProgressBar) -> bool:
        assert not self.built
        self.built = True

        if not self.ok:
            return False

        if len(self.source_files) == 0:
            self.ok = False
            if self.path.is_dir():
                bar.error(f"{self.short_path} is an empty directory.")
            else:
                bar.error(f"{self.path} does not exist.")
            return False

        # Check file names.
        for f in self.source_files:
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(f.name):
                self.ok = False
                bar.error(f"{str(f)} does not match file name regex {config.FILE_NAME_REGEX}")
                return False

        # Link all source_files
        if self.tmpdir.is_file():
            self.tmpdir.unlink()
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.input_files = []
        hashes = []
        for f in self.source_files:
            if not f.is_file():
                self.ok = False
                bar.error(f"{str(f)} is not a file")
                return False
            tmpf = self.tmpdir / f.name
            if (
                not self.substitute_constants
                or not self.problem.settings.constants
                or not has_substitute(f, config.CONSTANT_SUBSTITUTE_REGEX)
            ):
                ensure_symlink(tmpf, f)
            else:
                copy_and_substitute(
                    f,
                    tmpf,
                    self.problem.settings.constants,
                    pattern=config.CONSTANT_SUBSTITUTE_REGEX,
                    bar=bar,
                )
            self.input_files.append(tmpf)
            hashes.append(hash_file(tmpf))
        self.hash = combine_hashes(hashes)

        if not self._get_language(bar):
            return False

        self._checks(bar)

        # A file containing the compile command and hash.
        meta_path = self.tmpdir / "meta_.yaml"

        compile_command = self.language.compile or ""
        run_command = self.language.run

        if (
            self.subdir == "submissions"
            and config.args.sanitizer
            and self.language.name in SANITIZER_FLAGS
        ):
            sanitizer = SANITIZER_FLAGS[self.language.name]
            if "compile" in sanitizer:
                compile_command += " " + sanitizer["compile"]
            if "run" in sanitizer:
                run_command += " " + sanitizer["run"]

        self.compile_command = shlex.split(compile_command.format(**self.env))
        self.run_command = shlex.split(run_command.format(**self.env))

        # Compare the hash to the last build.
        up_to_date = False
        if meta_path.is_file():
            meta_yaml = read_yaml(meta_path)
            if isinstance(meta_yaml, dict):
                up_to_date = (
                    meta_yaml["hash"] == self.hash and meta_yaml["command"] == self.compile_command
                )

        if not up_to_date or config.args.force_build:
            if not self._compile(bar):
                return False

        if self.path in self.problem._program_callbacks:
            for c in self.problem._program_callbacks[self.path]:
                c(self)

        if "code" in self.limits:
            size = sum(f.stat().st_size for f in self.source_files)
            if size > self.limits["code"] * 1024:
                bar.warn(
                    f"Code limit exceeded (set limits.code to at least {(size + 1023) // 1024}KiB in problem.yaml)"
                )

        return True

    def _exec_command(self, *args: Any, **kwargs: Any) -> ExecResult:
        if "timeout" not in kwargs and "timeout" in self.limits:
            kwargs["timeout"] = self.limits["timeout"]
        if "memory" not in kwargs and "memory" in self.limits:
            kwargs["memory"] = self.limits["memory"]
        return exec_command(*args, **kwargs)

    @staticmethod
    def add_callback(problem: "Problem", path: Path, c: Callable[["Program"], Any]) -> None:
        if path not in problem._program_callbacks:
            problem._program_callbacks[path] = []
        problem._program_callbacks[path].append(c)


class Generator(Program):
    def __init__(self, problem: "Problem", path: Path, **kwargs: Any) -> None:
        super().__init__(
            problem,
            path,
            "generators",
            limits={"timeout": problem.limits.generator_time},
            substitute_constants=True,
            **kwargs,
        )

    # Run the generator in the given working directory.
    # May write files in |cwd| and stdout is piped to {name}.in if it's not written already.
    # Returns ExecResult. Success when result.status == ExecStatus.ACCEPTED.
    def run(
        self, bar: ProgressBar, cwd: Path, name: str, args: Sequence[str | Path] = []
    ) -> ExecResult:
        assert self.run_command is not None

        in_path = cwd / (name + ".in")
        stdout_path = cwd / (name + ".in_")

        # Clean the directory, but not the meta_.yaml file.
        for f in cwd.iterdir():
            if f.name == "meta_.yaml":
                continue
            if f.is_dir() and not f.is_symlink():
                shutil.rmtree(f)
            else:
                f.unlink()

        timeout = self.limits["timeout"]

        with stdout_path.open("w") as stdout_file:
            result = self._exec_command(
                [*self.run_command, *args],
                stdout=stdout_file,
                cwd=cwd,
            )

        if result.status == ExecStatus.TIMEOUT:
            # Timeout -> stop retrying and fail.
            bar.log(f"TIMEOUT after {timeout}s", color=Fore.RED)
            return result

        if not result.status:
            return result

        if stdout_path.read_text():
            if in_path.is_file():
                bar.warn(f"Generator wrote to both {name}.in and stdout. Ignoring stdout.")
            else:
                stdout_path.rename(in_path)
        else:
            if not in_path.is_file():
                bar.log(f"Did not write {name}.in and stdout is empty!", color=Fore.RED)
                result.status = ExecStatus.REJECTED
                return result

        return result
