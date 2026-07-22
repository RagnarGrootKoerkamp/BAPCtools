import hashlib
import os
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Optional, TYPE_CHECKING

from colorama import Fore

from bapctools import config, languages
from bapctools.util import (
    combine_hashes,
    copy_and_substitute,
    ensure_symlink,
    error,
    exec_command,
    ExecResult,
    ExecStatus,
    glob,
    has_substitute,
    hash_file,
    once,
    PrintBar,
    ProgressBar,
    read_yaml,
    remove_path,
    strip_newline,
    write_yaml,
)

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools.problem import Problem


@once
def create_aliases() -> None:
    h = hashlib.sha256(bytes(Path.cwd())).hexdigest()[-6:]
    tmpdir = (Path(tempfile.gettempdir()) / ("bapctools_" + h) / ".aliases").resolve()

    langs = languages.languages()
    bar = PrintBar()

    def create_alias(code: str, alias: str, use_compile: bool) -> None:
        fallback = False
        exe = None
        for lang in langs:
            if lang.code != code:
                continue
            if not lang.is_installed(bar):
                fallback = True
                continue
            exe = lang.compile_exe if use_compile else lang.run_exe
            if exe is None:
                continue
            language = lang
            break

        if language is None:
            bar.warn(f"Did not find required language {code}")
            return
        assert exe is not None
        exe = shutil.which(exe)
        assert exe is not None

        if fallback:
            language.warn_fallback(bar)

        alias_path = tmpdir / alias
        ensure_symlink(alias_path, Path(exe))
        bar.debug(f"Adding alias {alias}: {alias_path.as_posix()} -> {exe}")

    remove_path(tmpdir)
    tmpdir.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(tmpdir) + os.pathsep + os.environ["PATH"]

    create_alias("python3", "python3", use_compile=False)
    create_alias("c", "cc", use_compile=True)
    create_alias("cpp", "c++", use_compile=True)
    _alias_setup_complete = True


SANITIZER_FLAGS: Final[Mapping[str, Mapping[str, str]]] = {
    "cpp": {"compile": "-fsanitize=undefined,address"},
    "cppgmp": {"compile": "-fsanitize=undefined,address"},
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
        languages.languages()
        create_aliases()

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
        self.name: str = relpath.as_posix()
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
        self.language: languages.Language  # Populated in Program.build

    # checks all languages and sorts them
    def _get_language_candidates(
        self, bar: ProgressBar
    ) -> list[tuple[languages.Language, list[Path]]]:
        candidates = []
        for lang in languages.languages():
            score, matching = lang.evaluate(self.input_files)
            if matching:
                candidates.append((score, lang, matching))
        return [(lang, files) for _, lang, files in sorted(candidates, reverse=True)]

    def _get_entry_point(self, files: list[Path], bar: ProgressBar) -> tuple[Path, Path, str]:
        binary = self.tmpdir / languages.BINARY_NAME
        mainfile = None
        if not self.has_deps:
            assert files
            for f in sorted(files):
                if f.name.lower().startswith("main"):
                    mainfile = f
                    break
            if mainfile is None:
                mainfile = sorted(files)[0]
        else:
            mainfile = self.tmpdir / self.source_files[0].name
        mainclass = mainfile.with_suffix("").name
        return (binary, mainfile, str(mainclass))

    # Sets self.language and self.env['mainfile']
    def _get_language(self, bar: ProgressBar) -> bool:
        candidates = self._get_language_candidates(bar)

        fallback = False
        for lang, files in candidates:
            if not lang.is_installed(bar):
                fallback = True
                continue

            if fallback:
                lang.warn_fallback(bar)

            self.language = lang
            binary, mainfile, mainclass = self._get_entry_point(files, bar)
            self.env = {
                "path": str(self.tmpdir),
                # NOTE: This only contains files matching the winning language.
                "files": " ".join(str(f) for f in files),
                "binary": binary,
                "mainfile": mainfile,
                "mainclass": mainclass,
                "Mainclass": mainclass[0].upper() + mainclass[1:],
                # Memory limit in MB.
                "memlim": self.limits.get("memory", config.DEFAULT_MEMORY),
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
        if self.language.code in ("cpp", "cppgmp"):
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
            if self.language.code in ("cpp", "cppgmp"):
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
            if self.language.code in ("python2", "python3", "python3numpy"):
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
                remove_path(f)

        # The case where compile_command='{build}' will result in an empty list here.
        if not self.compile_command:
            return True

        remove_path(meta_path)
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
        for d in reversed(self.short_path.parents[:-1]):
            if not config.FILE_NAME_REGEX.fullmatch(d.name):
                self.ok = False
                bar.error(
                    f"{str(d)} does not match directory name regex {config.FILE_NAME_REGEX.pattern}"
                )
                return False
        for f in self.source_files:
            if not config.FILE_NAME_REGEX.fullmatch(f.name):
                self.ok = False
                bar.error(
                    f"{str(f)} does not match file name regex {config.FILE_NAME_REGEX.pattern}"
                )
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
            and self.language.code in SANITIZER_FLAGS
        ):
            sanitizer = SANITIZER_FLAGS[self.language.code]
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
            remove_path(f)

        with stdout_path.open("w") as stdout_file:
            result = self._exec_command(
                [*self.run_command, *args],
                stdout=stdout_file,
                cwd=cwd,
            )

        if result.status == ExecStatus.TIMEOUT:
            # Timeout -> stop retrying and fail.
            timeout = self.limits["timeout"]
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
