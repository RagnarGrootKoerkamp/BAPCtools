import collections
import itertools
import random
import re
import secrets
import shlex
import shutil
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import cast, Final, Literal, Optional, overload, TypeVar

from colorama import Fore, Style
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from bapctools import config, parallel, program, run, validate, visualize
from bapctools.problem import Problem
from bapctools.testcase import Testcase
from bapctools.util import (
    combine_hashes,
    combine_hashes_dict,
    ensure_symlink,
    eprint,
    error,
    ExecResult,
    ExecStatus,
    fatal,
    get_basedirs,
    glob,
    hash_file_content,
    hash_string,
    is_relative_to,
    log,
    path_size,
    PrintBar,
    ProgressBar,
    read_yaml,
    ryaml_get_or_add,
    shorten_path,
    substitute,
    warn,
    write_yaml,
)
from bapctools.verdicts import Verdict

YAML_TYPE = Optional[str | dict[object, object]]

INCLUSIVE_RANGE_REGEX = re.compile(r"^(-?\d+)\.\.=(-?\d+)$")


class ParseException(Exception):
    def __init__(self, message: Optional[str] = None, path: Optional[Path | str] = None) -> None:
        super().__init__(message, path)
        self.message = message
        self.path = path


def assert_type(
    name: str,
    obj: object,
    types: tuple[type[object], ...] | type[object],
    path: Optional[Path] = None,
) -> None:
    if isinstance(obj, types):
        return
    if not isinstance(types, tuple):
        types = (types,)
    named_types = " or ".join("None" if t is None else t.__name__ for t in types)
    raise ParseException(
        f"{name} must be of type {named_types}, found {obj.__class__.__name__}: {obj}",
        path,
    )


UNIQUE_TESTCASE_KEYS: Final[Sequence[str]] = (
    "copy",
    "generate",
    "count",
    "match",
    *(e[1:] for e in config.KNOWN_TEXT_DATA_EXTENSIONS),
)


def is_testcase(yaml: YAML_TYPE) -> bool:
    return (
        yaml is None
        or isinstance(yaml, str)
        or (isinstance(yaml, dict) and any(key in yaml for key in UNIQUE_TESTCASE_KEYS))
    )


def is_directory(yaml: YAML_TYPE) -> bool:
    return isinstance(yaml, dict) and not is_testcase(yaml)


def has_count(yaml: YAML_TYPE) -> bool:
    return (
        isinstance(yaml, dict) and "count" in yaml and isinstance(yaml["count"], (int, list, str))
    )


# Returns the given path relative to the problem root.
def resolve_path(path_str: str, *, allow_absolute: bool, allow_relative: bool) -> Path:
    assert isinstance(path_str, str)
    path = PurePosixPath(path_str)
    if not allow_absolute:
        if path.is_absolute():
            raise ParseException(f"Path must not be absolute: {path}")

    if not allow_relative:
        if not path.is_absolute():
            raise ParseException(f"Path must be absolute: {path}")

    # Make all paths relative to the problem root.
    if path.is_absolute():
        return Path(*path.parts[1:])
    return Path("generators") / path


# An Invocation is a program with command line arguments to execute.
# The following classes inherit from Invocation:
# - GeneratorInvocation
# - SolutionInvocation
class Invocation:
    SEED_REGEX: Final[re.Pattern[str]] = re.compile(r"\{seed(:[0-9]+)?\}")
    NAME_REGEX: Final[re.Pattern[str]] = re.compile(r"\{name\}")

    # `string` is the name of the submission (relative to generators/ or absolute from the problem root) with command line arguments.
    # A direct path may also be given.
    def __init__(
        self,
        problem: Problem,
        string: str,
        *,
        allow_absolute: bool,
        allow_relative: bool = True,
    ) -> None:
        commands = shlex.split(string)
        command = commands[0]
        self.args = commands[1:]
        self.problem = problem

        # The original command string, used for caching invocation results.
        self.command_string = string

        # The name of the program to be executed, relative to the problem root.
        self.program_path = resolve_path(
            command, allow_absolute=allow_absolute, allow_relative=allow_relative
        )

        # NOTE: This is also used by `fuzz`.
        self.uses_seed = self.SEED_REGEX.search(self.command_string)

        # Make sure that {seed} occurs at most once.
        seed_cnt = 0
        for arg in self.args:
            seed_cnt += len(self.SEED_REGEX.findall(arg))
        if seed_cnt > 1:
            raise ParseException("{seed(:[0-9]+)} may appear at most once.")

        # Automatically set self.program when that program has been built.
        self.program: Optional[program.Generator | run.Submission] = None

        def callback(prog: program.Program) -> None:
            assert isinstance(prog, (program.Generator, run.Submission))
            self.program = prog

        program.Program.add_callback(problem, problem.path / self.program_path, callback)

    # Return the form of the command used for caching.
    # This is independent of {name} and the actual run_command.
    def cache_command(self, seed: Optional[int] = None) -> str:
        command_string = self.command_string
        if seed:
            command_string = self.SEED_REGEX.sub(str(seed), command_string)
        return command_string

    def hash(self, seed: Optional[int] = None) -> str:
        list = []
        if self.program is not None:
            assert self.program.hash is not None
            list.append(self.program.hash)
        list.append(self.cache_command(seed))
        return combine_hashes(list)

    # Return the full command to be executed.
    def _sub_args(self, *, seed: Optional[int] = None) -> Sequence[str]:
        if self.uses_seed:
            assert seed is not None

        def sub(arg: str) -> str:
            arg = self.NAME_REGEX.sub("testcase", arg)
            if self.uses_seed:
                arg = self.SEED_REGEX.sub(str(seed), arg)
            return arg

        return [sub(arg) for arg in self.args]


class GeneratorInvocation(Invocation):
    def __init__(self, problem: Problem, string: str) -> None:
        super().__init__(problem, string, allow_absolute=False)

    # Try running the generator |retries| times, incrementing seed by 1 each time.
    def run(
        self, bar: ProgressBar, cwd: Path, name: str, seed: int, retries: int = 1
    ) -> ExecResult:
        assert isinstance(self.program, program.Generator), "Generator program must be built!"

        for retry in range(retries):
            result = self.program.run(
                bar, cwd, name, args=self._sub_args(seed=(seed + retry) % 2**31)
            )
            if result.status:
                break
            if result.status == ExecStatus.TIMEOUT:
                break

        if not result.status:
            if retries > 1:
                bar.debug(f"{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}")
                bar.error(f"Generator crashed {retry + 1} times", result.err)
            else:
                bar.debug(f"{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}")
                bar.error("Generator crashed", result.err)

        if result.status and config.args.error and result.err:
            bar.log("stderr", result.err)

        return result


class SolutionInvocation(Invocation):
    def __init__(self, problem: Problem, string: str) -> None:
        super().__init__(problem, string, allow_absolute=True, allow_relative=False)

    # Run the submission, reading testcase.in from stdin and piping stdout to testcase.ans.
    # If the .ans already exists, nothing is done
    def run(self, bar: ProgressBar, cwd: Path) -> ExecResult:
        assert isinstance(self.program, run.Submission), "Submission program must be built!"

        in_path = cwd / "testcase.in"
        ans_path = cwd / "testcase.ans"

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        result = self.program.run(
            in_path, ans_path, args=self.args, cwd=cwd, generator_timeout=True
        )

        if result.status == ExecStatus.TIMEOUT:
            bar.debug(f"{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}")
            bar.error(f"Solution TIMEOUT after {result.duration}s")
        elif not result.status:
            bar.debug(f"{Style.RESET_ALL}-> {shorten_path(self.problem, cwd)}")
            bar.error("Solution crashed", result.err)

        if result.status and config.args.error and result.err:
            bar.log("stderr", result.err)
        return result

    def generate_interaction(self, bar: ProgressBar, cwd: Path, t: "TestcaseRule") -> bool:
        in_path = cwd / "testcase.in"
        interaction_path = cwd / "testcase.interaction"
        interaction_path.unlink(missing_ok=True)

        testcase = Testcase(self.problem, in_path, short_path=(t.path.parent / (t.name + ".in")))
        assert isinstance(self.program, run.Submission)
        r = run.Run(self.problem, self.program, testcase)

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        result = r.run(bar, interaction=interaction_path, submission_args=self.args)
        if result.verdict != Verdict.ACCEPTED:
            bar.error(f"could not generate .interaction, submission got {result.verdict}")
            return False

        return True


# Return absolute path to default submission, starting from the submissions directory.
# This function will always prints a message.
# Which submission is used is implementation defined, unless one is explicitly given on the command line.
def default_solution_path(generator_config: "GeneratorConfig") -> Path:
    problem = generator_config.problem
    solution = None
    stored_solution = problem.tmpdir / ".default_solution"
    bar = PrintBar("generators.yaml")
    if config.args.default_solution:
        if generator_config.has_yaml:
            bar.warn(
                f"""--default-solution Ignored. Set the default solution in the generators.yaml!
solution: /{config.args.default_solution}"""
            )
        else:
            solution = problem.path / config.args.default_solution
    else:
        # Use one of the accepted submissions.
        solutions = list(glob(problem.path, "submissions/accepted/*"))
        if len(solutions) == 0:
            fatal("No solution specified and no accepted submissions found.")

        # always try to take the same solution to not mess with hashing
        if stored_solution.is_file():
            old_solution = Path(stored_solution.read_text().strip())
            if old_solution in solutions:
                solution = old_solution
        if solution is None:
            solution = random.choice(solutions)

        solution_short_path = solution.relative_to(problem.path / "submissions")

        if generator_config.has_yaml:
            yaml_path = problem.path / "generators" / "generators.yaml"
            raw = yaml_path.read_text()
            raw = f"solution: /{solution.relative_to(problem.path)}\n" + raw
            yaml_path.write_text(raw)
            bar.log(
                f"No solution specified. {solution_short_path} added as default solution in the generators.yaml"
            )
        else:
            log(
                f"""No solution specified. Selected {solution_short_path}. Use
--default_solution {solution.relative_to(problem.path)}
to use a specific solution."""
            )
    assert solution
    stored_solution.write_text(str(solution))
    return Path("/") / solution.relative_to(problem.path)


KNOWN_TESTCASE_KEYS: Final[Sequence[str]] = (
    "type",
    "solution",
    "random_salt",
    "retries",
    *UNIQUE_TESTCASE_KEYS,
)
UNIQUE_DIRECTORY_KEYS: Final[Sequence[str]] = ("data", "test_group.yaml", "include")
KNOWN_DIRECTORY_KEYS: Final[Sequence[str]] = (
    "type",
    "solution",
    "random_salt",
    "retries",
    *UNIQUE_DIRECTORY_KEYS,
)
RESERVED_DIRECTORY_KEYS: Final[Sequence[str]] = ("command",)
KNOWN_ROOT_KEYS: Final[Sequence[str]] = ("generators", "version")
DEPRECATED_ROOT_KEYS: Final[Sequence[str]] = (
    "gitignore_generated",
    "parallel",
    "visualizer",
)


# Holds all inheritable configuration options. Currently:
# - config.solution
# - config.random_salt
# - config.retries
class Config:
    # Used at each directory or testcase level.

    @staticmethod
    def _parse_solution(p: Problem, x: object, path: Path) -> Optional[SolutionInvocation]:
        assert_type("solution", x, (type(None), str), path)
        if x is None:
            return None
        return SolutionInvocation(p, cast(str, x))

    @staticmethod
    def _parse_random_salt(x: object, path: Path) -> str:
        assert_type("random_salt", x, (type(None), str), path)
        if x is None:
            return ""
        return cast(str, x)

    @staticmethod
    def _parse_retries(x: object, path: Path) -> int:
        assert_type("retries", x, (type(None), int), path)
        if x is None:
            return 1
        return cast(int, x)

    def __init__(
        self,
        problem: Problem,
        path: Path,
        yaml: Optional[dict[object, object]] = None,
        parent_config: Optional["Config"] = None,
    ) -> None:
        if parent_config is None:
            self.needs_default_solution = True
            self.solution: Optional[SolutionInvocation] = None
            self.random_salt: str = ""
            self.retries: int = 1
        else:
            for key, value in vars(parent_config).items():
                setattr(self, key, value)

        if yaml is not None:
            if "solution" in yaml:
                self.needs_default_solution = False
                self.solution = Config._parse_solution(problem, yaml["solution"], path)
            if "random_salt" in yaml:
                self.random_salt = Config._parse_random_salt(yaml["random_salt"], path)
            if "retries" in yaml:
                self.retries = Config._parse_retries(yaml["retries"], path)


class Rule:
    # key: the dictionary key in the yaml file, i.e. `testcase`
    # name: the numbered testcase name, i.e. `01-testcase`
    def __init__(
        self,
        problem: Problem,
        key: str,
        name: str,
        yaml: YAML_TYPE,
        parent: "AnyDirectory",
    ) -> None:
        self.parent = parent

        # Yaml key of the current directory/testcase.
        self.key = key
        # Filename of the current directory/testcase.
        self.name: str = name
        # Path of the current directory/testcase relative to data/.
        self.path: Path = parent.path / self.name
        # store Yaml
        self.yaml = yaml

        if parent.config is not None:
            self.config: Config = parent.config
        else:
            self.config = Config(problem, parent.path / name)
        if isinstance(yaml, dict):
            self.config = Config(problem, parent.path / name, yaml, parent_config=parent.config)


class TestcaseRule(Rule):
    def __init__(
        self,
        problem: Problem,
        generator_config: "GeneratorConfig",
        key: str,
        name: str,
        yaml: YAML_TYPE,
        parent: "AnyDirectory",
        count_value: int,
    ) -> None:
        assert is_testcase(yaml)

        # if not None rule will be skipped during generation
        self.parse_error: Optional[str] = None

        # root in /data
        self.root = (parent.path / name).parts[0]
        # Whether this testcase is a sample.
        self.sample: bool = self.root == "sample"
        # each test case needs some kind of input
        self.required_in: list[list[str]] = [[".in"]]
        if self.sample:
            # for samples a statement in file is also sufficient
            self.required_in.append([".in.statement"])
            if problem.interactive or problem.multi_pass:
                # if .interaction is supported that is also fine as long as input download is provided as well.
                self.required_in.append([".interaction", ".in.download"])

        # 1. Generator
        self.generator = None
        # 2. Files are copied form this path.
        #    This variable already includes the .in extension, so `.with_suffix()` works nicely.
        self.copy = None
        # 3. Hardcoded cases where the source is in the yaml file itself.
        self.hardcoded = dict[str, str]()
        # map of ext to list of patterns used to check the generated testcase.<ext>
        self.patterns = collections.defaultdict[str, list[re.Pattern[str]]](list)

        # Hash of testcase for caching.
        self.hash: str

        # Yaml of rule
        self.rule = dict[str, str | int]()

        # Used by `fuzz`
        self.in_is_generated = False
        self.count_value = count_value

        # used to decide if this was supposed to be a duplicate or not
        self.intended_copy = has_count(yaml)

        # used to handle duplicated testcase rules
        self.copy_of = None

        # set during generate
        self.generate_success = False

        self.process = generator_config.process_testcase(parent.path / name)

        bar = PrintBar("generators.yaml", item=parent.path / name)

        if name.endswith(".in"):
            bar.error("Testcase names should not end with '.in'")
            name = name[:-3]

        try:
            super().__init__(problem, key, name, yaml, parent)
            bar = bar.start(self.path)

            # files to consider for hashing
            hashes = {}
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(name + ".in"):
                raise ParseException("Test case does not have a valid name.")

            if name == "test_group":
                raise ParseException(
                    "Test case must not be named 'test_group', this clashes with the group-level 'test_group.yaml'."
                )

            if yaml is None:
                raise ParseException(
                    "Empty yaml entry (Testcases must be generated not only mentioned)."
                )
            else:
                assert_type("testcase", yaml, (str, dict))
                if isinstance(yaml, str):
                    yaml = {"generate": yaml}
                    if isinstance(yaml["generate"], str) and yaml["generate"].endswith(".in"):
                        bar.warn(
                            f"Use the new `copy: path/to/case` key instead of {yaml['generate']}."
                        )
                        yaml = {"copy": yaml["generate"][:-3]}

                # checks
                satisfied = False
                msg = []
                for required in [[".generate"], [".copy"]] + self.required_in:
                    satisfied = satisfied or all(x[1:] in yaml for x in required)
                    msg.append(" and ".join([x[1:] for x in required]))
                if not satisfied:
                    raise ParseException(f"Testcase requires at least one of: {', '.join(msg)}.")
                if not problem.interactive and not problem.multi_pass and "interaction" in yaml:
                    raise ParseException(
                        "Testcase cannot have 'interaction' key for non-interactive/non-multi-pass problem."
                    )
                if not self.sample:
                    for ext in config.KNOWN_SAMPLE_TESTCASE_EXTENSIONS:
                        if ext[1:] in yaml:
                            raise ParseException(f"Non sample testcase cannot use '{ext[1:]}")
                if "submission" in yaml and "ans" in yaml:
                    raise ParseException("Testcase cannot specify both 'submissions' and 'ans'.")

                # 1. generate
                if "generate" in yaml:
                    command_string = yaml["generate"]
                    assert_type("generate", command_string, str)
                    assert isinstance(command_string, str)
                    if len(command_string) == 0:
                        raise ParseException("'generate' must not be empty.")

                    # first replace {{constants}}
                    command_string = substitute(
                        command_string,
                        problem.settings.constants,
                        pattern=config.CONSTANT_SUBSTITUTE_REGEX,
                    )

                    # then replace {count} and {seed}
                    if "{count}" in command_string:
                        if has_count(yaml):
                            command_string = command_string.replace(
                                "{count}", f"{self.count_value}"
                            )
                            self.intended_copy = False
                        else:
                            bar.warn(
                                "Found {count} in generator command but no count in yaml. Ignored."
                            )
                    self.generator = GeneratorInvocation(problem, command_string)

                    # IMPORTANT: The seed depends on white space, but
                    # leading and trailing whitespace is stripped.
                    seed_value = self.config.random_salt
                    if self.count_value != 1:  # distinguish different count values
                        # IMPORTANT: We need to use `self.count_value - 1` for backwards compatibility.
                        seed_value += f":{self.count_value - 1}"
                    seed_value += self.generator.command_string.strip()
                    self.seed = int(hash_string(seed_value), 16) % 2**31
                    self.in_is_generated = True
                    self.rule["gen"] = self.generator.command_string
                    if self.generator.uses_seed:
                        self.rule["seed"] = self.seed
                        self.intended_copy = False
                    hashes[".in"] = self.generator.hash(self.seed)

                # 2. path
                if "copy" in yaml:
                    copy_entry = yaml["copy"]
                    assert_type("`copy`", copy_entry, str)
                    assert isinstance(copy_entry, str)
                    if Path(copy_entry).suffix in config.KNOWN_TEXT_DATA_EXTENSIONS:
                        bar.warn(f"`copy: {copy_entry}` should not include the extension.")
                    self.copy = resolve_path(copy_entry, allow_absolute=False, allow_relative=True)
                    self.copy = problem.path / self.copy.parent / (self.copy.name + ".in")
                    if self.copy.is_file():
                        self.in_is_generated = False
                    self.rule["copy"] = str(self.copy)
                    for ext in config.KNOWN_TESTCASE_EXTENSIONS:
                        if self.copy.with_suffix(ext).is_file():
                            hashes[ext] = hash_file_content(self.copy.with_suffix(ext))

                # 3. hardcoded strings (or, for the Test Case Configuration, a yaml mapping)
                for ext in config.KNOWN_TEXT_DATA_EXTENSIONS:
                    if ext[1:] in yaml:
                        value = yaml[ext[1:]]
                        if ext == ".yaml":
                            assert_type(ext, value, dict)
                            value = write_yaml(value)
                            assert value is not None
                        else:
                            assert_type(ext, value, str)
                        assert isinstance(value, str)
                        if len(value) > 0 and value[-1] != "\n":
                            value += "\n"
                        self.hardcoded[ext] = value

                if ".in" in self.hardcoded:
                    self.in_is_generated = False
                    self.rule["in"] = self.hardcoded[".in"]
                for ext, value in self.hardcoded.items():
                    hashes[ext] = hash_string(value)

                if "match" in yaml:
                    match_entries = yaml["match"]
                    assert_type("`match`", match_entries, (list, dict, str))
                    if isinstance(match_entries, str):
                        match_entries = [match_entries]
                    if isinstance(match_entries, list):
                        match_entries = {"in": match_entries}
                    assert isinstance(match_entries, dict)

                    for ext, entries in match_entries.items():
                        if ext not in ["in", "ans"]:
                            if config.args.action == "generate":
                                bar.log(f"Unknown match key: {ext}")
                            continue

                        if isinstance(entries, str):
                            entries = [entries]

                        assert_type(f"`match.{ext}`", entries, list)
                        for i, entry in enumerate(entries):
                            assert_type(f"`match.{ext}[{i}]`", entry, str)
                            try:
                                self.patterns[ext].append(
                                    re.compile(entry, re.MULTILINE | re.DOTALL)
                                )
                            except re.error:
                                raise ParseException(f"could not parse regex `match.{ext}[{i}]`.")

            # Warn/Error for unknown keys.
            for any_key in yaml:
                if any_key in UNIQUE_DIRECTORY_KEYS:
                    raise ParseException(f"Testcase must not contain reserved key {any_key}.")
                if any_key not in KNOWN_TESTCASE_KEYS:
                    if config.args.action == "generate":
                        bar.log(f"Unknown testcase level key: {any_key}")

            # combine hashes
            self.hash = combine_hashes_dict(hashes)

            if self.hash in generator_config.rules_cache:
                self.copy_of = generator_config.rules_cache[self.hash]
                if id(self.copy_of.yaml) != id(self.yaml):
                    self.intended_copy = False
            else:
                generator_config.rules_cache[self.hash] = self

            if not any(all(ext in hashes for ext in required) for required in self.required_in):
                generator_config.n_parse_error += 1
                # An error is shown during generate.

        except ParseException as e:
            # For testcases we can handle the parse error locally since this does not influence much else
            self.parse_error = e.message
            generator_config.n_parse_error += 1

    def _has_required_in(t, infile: Path) -> bool:
        for required in t.required_in:
            if all(infile.with_suffix(ext).is_file() for ext in required):
                return True
        return False

    class MetaYaml:
        def __init__(self, problem: Problem, testcase: "TestcaseRule") -> None:
            self._path = problem.tmpdir / "data" / testcase.hash / "meta_.yaml"
            data = read_yaml(self._path, suppress_errors=True) if self._path.is_file() else {}
            if not isinstance(data, dict):
                data = {}

            T = TypeVar("T")

            def get(key: str, default: T) -> T:
                value = data.get(key, default)
                return value if isinstance(value, type(default)) else default

            self.rule_hashes: dict[object, object] = get("rule_hashes", {})
            self.generated_extensions: list[object] = get("generated_extensions", [])
            self.input_validator_hashes: dict[object, object] = get("input_validator_hashes", {})
            self.matches: dict[object, object] = get("matches", {})
            self.solution_hash: dict[object, object] = get("solution_hash", {})
            self.interactor_hash: dict[object, object] = get("interactor_hash", {})
            self.ans_out_validator_hashes: dict[object, object] = get(
                "ans_out_validator_hashes", {}
            )
            self.visualizer_hash: dict[object, object] = get("visualizer_hash", {})
            self.rule = testcase.rule

        def write(self) -> None:
            data = {k: v for k, v in vars(self).items() if not k.startswith("_")}
            write_yaml(data, self._path)

    def link(
        t,
        problem: Problem,
        generator_config: "GeneratorConfig",
        bar: ProgressBar,
        dst: Path,
    ) -> None:
        assert t.process

        src_dir = problem.path / "data" / t.path.parent
        src = src_dir / (t.name + ".in")

        for ext in config.KNOWN_DATA_EXTENSIONS:
            source = src.with_suffix(ext)
            target = dst.with_suffix(ext)

            if source.is_file() and source in generator_config.known_files:
                generator_config.known_files.add(target)
                if target.is_file():
                    if target.is_symlink() and target.resolve() == source.resolve():
                        # identical -> skip
                        pass
                    else:
                        # different -> overwrite
                        generator_config.remove(target)
                        ensure_symlink(target, source, relative=True)
                        bar.log(f"CHANGED: {target.name}")
                else:
                    # new file -> copy it
                    ensure_symlink(target, source, relative=True)
                    bar.log(f"NEW: {target.name}")
            elif target.is_file():
                # Target exists but source wasn't generated -> remove it
                generator_config.remove(target)
                bar.log(f"REMOVED: {target.name}")
            else:
                # both source and target do not exist
                pass

    def validate_in(
        t,
        problem: Problem,
        testcase: Testcase,
        meta_yaml: "TestcaseRule.MetaYaml",
        bar: ProgressBar,
    ) -> bool:
        assert t.process

        infile = problem.tmpdir / "data" / t.hash / "testcase.in"
        assert infile.is_file()

        if testcase.root == "testing_tool_test":
            return True

        input_validator_hashes = testcase.validator_hashes(validate.InputValidator, bar)
        if all(h in meta_yaml.input_validator_hashes for h in input_validator_hashes):
            return True

        if not testcase.validate_format(
            validate.Mode.INPUT,
            bar=bar,
            constraints=None,
            warn_instead_of_error=config.args.no_validators,
        ):
            if not config.args.no_validators:
                if t.generator:
                    bar.warn(
                        "Failed generator command: "
                        + (
                            " ".join(
                                [
                                    str(t.generator.program_path),
                                    *t.generator._sub_args(seed=t.seed),
                                ]
                            )
                            if t.generator.uses_seed
                            else t.generator.command_string
                        ),
                    )
                bar.debug("Use generate --no-validators to ignore validation results.")
                bar.done(False)
                return False
        else:
            for h in input_validator_hashes:
                meta_yaml.input_validator_hashes[h] = input_validator_hashes[h]
            meta_yaml.write()
        return True

    def validate_ans_and_out(
        t,
        problem: Problem,
        testcase: Testcase,
        meta_yaml: "TestcaseRule.MetaYaml",
        bar: ProgressBar,
    ) -> bool:
        assert t.process

        infile = problem.tmpdir / "data" / t.hash / "testcase.in"
        assert infile.is_file()

        if testcase.root in ["invalid_input", "testing_tool_test"]:
            return True

        ansfile = infile.with_suffix(".ans")
        if not ansfile.is_file():
            bar.error("No .ans file was generated!")
            return False

        outfile = infile.with_suffix(".out")
        if not outfile.is_file() and testcase.root in [
            "invalid_output",
            "valid_output",
        ]:
            bar.error("No .out file was generated!")
            return False

        ans_out_validator_hashes = testcase.validator_hashes(validate.AnswerValidator, bar).copy()
        output_validator_hashes = testcase.validator_hashes(validate.OutputValidator, bar)

        mode = validate.Mode.ANSWER
        if testcase.root == "invalid_answer":
            mode = validate.Mode.INVALID
        elif testcase.root == "invalid_output":
            ans_out_validator_hashes.update(output_validator_hashes)
            mode = validate.Mode.INVALID
        elif testcase.root == "valid_output" or outfile.is_file():
            ans_out_validator_hashes.update(output_validator_hashes)
            mode = validate.Mode.VALID_OUTPUT

        if all(h in meta_yaml.ans_out_validator_hashes for h in ans_out_validator_hashes):
            return True

        if not testcase.validate_format(
            mode,
            bar=bar,
            warn_instead_of_error=config.args.no_validators,
        ):
            if not config.args.no_validators:
                bar.debug("Use generate --no-validators to ignore validation results.")
                bar.done(False)
                return False
        else:
            for h in ans_out_validator_hashes:
                meta_yaml.ans_out_validator_hashes[h] = ans_out_validator_hashes[h]
            meta_yaml.visualizer_hash = {}
            meta_yaml.write()
        return True

    def generate(
        t,
        problem: Problem,
        generator_config: "GeneratorConfig",
        parent_bar: ProgressBar,
    ) -> None:
        assert t.process

        bar = parent_bar.start(str(t.path))
        generator_config.failed += 1

        if t.copy_of is not None and not t.intended_copy:
            bar.warn(
                f'Found identical rule at {t.copy_of.path}. Use "count: <int>" if you want identical testcases (do not use {{seed}} or {{count}}).'
            )

        # Some early checks.
        if t.copy_of is not None and not t.copy_of.generate_success:
            bar.done(False, f"See {t.copy_of.path}. Skipping.")
            return
        if t.parse_error is not None:
            bar.done(False, f"{t.parse_error} Skipping.")
            return
        if t.generator and t.generator.program is None:
            bar.done(False, "Generator didn't build. Skipping.")
            return

        target_dir = problem.path / "data" / t.path.parent
        target_infile = target_dir / (t.name + ".in")

        # E.g. bapctmp/problem/data/<hash>.in
        cwd = problem.tmpdir / "data" / t.hash
        cwd.mkdir(parents=True, exist_ok=True)
        infile = cwd / "testcase.in"
        ansfile = cwd / "testcase.ans"
        meta_yaml = TestcaseRule.MetaYaml(problem, t)

        def _check_deterministic(tmp: Path, tmp_infile: Path) -> None:
            assert t.generator is not None
            result = t.generator.run(bar, tmp, tmp_infile.stem, t.seed, t.config.retries)
            if not result.status:
                return

            # Now check that the source and target are equal.
            if infile.read_bytes() == tmp_infile.read_bytes():
                if config.args.check_deterministic:
                    bar.part_done(True, "Generator is deterministic.")
            else:
                bar.part_done(
                    False,
                    f"Generator `{t.generator.command_string}` is not deterministic.",
                )

            # If {seed} is used, check that the generator depends on it.
            if t.generator.uses_seed:
                depends_on_seed = False
                for run in range(config.SEED_DEPENDENCY_RETRIES):
                    new_seed = (t.seed + 1 + run) % (2**31)
                    result = t.generator.run(bar, tmp, tmp_infile.stem, new_seed, t.config.retries)
                    if not result.status:
                        return

                    # Now check that the source and target are different.
                    if infile.read_bytes() != tmp_infile.read_bytes():
                        depends_on_seed = True
                        break

                if depends_on_seed:
                    if config.args.check_deterministic:
                        bar.debug("Generator depends on seed.")
                else:
                    bar.log(
                        f"Generator `{t.generator.command_string}` likely does not depend on seed:",
                        f"All values in [{t.seed}, {new_seed}] give the same result.",
                    )

        # For each generated .in file check that they
        # use a deterministic generator by rerunning the generator with the
        # same arguments.  This is done when --check-deterministic is passed,
        # which is also set to True when running `bt all`.
        # This doesn't do anything for non-generated cases.
        # It also checks that the input changes when the seed changes.
        def check_deterministic(force: bool = False) -> None:
            if not force and not config.args.check_deterministic:
                return
            if t.generator is None:
                return

            # Check that the generator is deterministic.
            # TODO: Can we find a way to easily compare cpython vs pypy? These
            # use different but fixed implementations to hash tuples of ints.
            tmp = cwd / "tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            tmp_infile = tmp / "testcase.in"
            _check_deterministic(tmp, tmp_infile)
            # clean up
            shutil.rmtree(tmp)

        def generate_from_rule() -> bool:
            nonlocal meta_yaml

            # create expected cache entry for generate
            rule_hashes = dict[object, object]()
            if t.copy:
                rule_hashes["source_hash"] = t.hash
            for ext, string in t.hardcoded.items():
                rule_hashes["hardcoded_" + ext[1:]] = hash_string(string)
            if t.generator:
                rule_hashes["generator_hash"] = t.generator.hash(seed=t.seed)
                rule_hashes["generator"] = t.generator.cache_command(seed=t.seed)

            if not infile.is_file() or meta_yaml.rule_hashes != rule_hashes:
                # clear all generated files
                shutil.rmtree(cwd, ignore_errors=True)
                cwd.mkdir(parents=True, exist_ok=True)
                meta_yaml = TestcaseRule.MetaYaml(problem, t)

                # Step 1: run `generate:` if present.
                if t.generator:
                    result = t.generator.run(bar, cwd, infile.stem, t.seed, t.config.retries)
                    if result.err is not None:
                        bar.debug("generator:", result.err)
                    if not result.status:
                        return False

                # Step 2: Copy `copy:` files for all known extensions.
                if t.copy:
                    # We make sure to not silently overwrite changes to files in data/
                    # that are copied from generators/.
                    copied = False
                    for ext in config.KNOWN_DATA_EXTENSIONS:
                        ext_file = t.copy.with_suffix(ext)
                        if ext_file.is_file():
                            shutil.copy(ext_file, infile.with_suffix(ext), follow_symlinks=True)
                            copied = True
                    if not copied:
                        bar.warn(f"No files copied from {t.copy}.")

                # Step 3: Write hardcoded files.
                for ext, contents in t.hardcoded.items():
                    # substitute in contents? -> No!
                    infile.with_suffix(ext).write_text(contents)

                # Step 4: Error if infile was not generated.
                if not t._has_required_in(infile):
                    msg = ", ".join(" and ".join(required) for required in t.required_in)
                    bar.error(f"No {msg} file was generated!")
                    return False

                # Step 5: save which files where generated
                meta_yaml.generated_extensions = [
                    ext for ext in config.KNOWN_DATA_EXTENSIONS if infile.with_suffix(ext).is_file()
                ]

                # Step 6: update cache
                meta_yaml.rule_hashes = rule_hashes
                meta_yaml.write()

                # Step 7: check deterministic:
                check_deterministic(True)
            else:
                check_deterministic(False)

            assert t._has_required_in(infile), f"Failed to generate in file: {infile.name}"
            return True

        def check_match(testcase: Testcase, ext: str, bar: ProgressBar) -> None:
            nonlocal meta_yaml

            updated = False
            cache = meta_yaml.matches.get(ext)
            if not isinstance(cache, dict):
                cache = {}
                meta_yaml.matches[ext] = cache
                updated = True

            text: Optional[str] = None
            for pattern in t.patterns[ext]:
                name = pattern.pattern.encode("unicode_escape").decode()

                if name not in cache:
                    if text is None:
                        file = testcase.in_path.with_suffix(f".{ext}")
                        assert file.is_file()
                        text = file.read_text()
                    match = pattern.search(text)
                    cache[name] = f"[{match.start()}, {match.end()})" if match else None
                    updated = True

                if cache[name]:
                    bar.debug(f"Found match for '{name}'': {cache[name]}")
                else:
                    bar.warn(f"Found not match for '{name}'")

            if updated:
                meta_yaml.write()

        def generate_from_solution(testcase: Testcase, bar: ProgressBar) -> bool:
            nonlocal meta_yaml

            if testcase.root in [
                *config.INVALID_CASE_DIRECTORIES,
                "valid_output",
                "testing_tool_test",
            ]:
                return True
            if config.args.no_solution:
                return True

            if t.config.solution is not None:
                solution_hash: dict[object, object] = {
                    "solution_hash": t.config.solution.hash(),
                    "solution": t.config.solution.cache_command(),
                }
            else:
                solution_hash = {
                    "solution_hash": None,
                    "solution": None,
                }

            def needed(
                ext: str, interactor_hash: Optional[dict[str, dict[str, str]]] = None
            ) -> bool:
                if ext in meta_yaml.generated_extensions:
                    return False
                if not infile.with_suffix(ext).is_file():
                    return True
                if interactor_hash is not None and meta_yaml.interactor_hash != interactor_hash:
                    return True
                return meta_yaml.solution_hash != solution_hash

            used_solution = False
            changed_ans = False
            if not problem.settings.ans_is_output:
                # Generate empty ans file
                if ".ans" not in meta_yaml.generated_extensions:
                    if not ansfile.is_file() and (problem.interactive or problem.multi_pass):
                        ansfile.write_text("")
                        changed_ans = True
                # For interactive/multi-pass problems, run the solution and generate a .interaction if necessary.
                if problem.interactive or problem.multi_pass:
                    interactor_hash = testcase.validator_hashes(validate.OutputValidator, bar)
                    if (
                        t.config.solution
                        and (testcase.root == "sample" or config.args.interaction)
                        and needed(".interaction", interactor_hash)
                        and not any(
                            infile.with_suffix(ext).is_file()
                            for ext in [".out", ".in.statement", ".ans.statement"]
                        )
                    ):
                        if not t.config.solution.generate_interaction(bar, cwd, t):
                            return False
                        used_solution = True
                        # We need the cast, because key/value types in dicts are invariant,
                        # but it is safe to cast a dict with more specific types to a dict with less specific types.
                        meta_yaml.interactor_hash = cast(dict[object, object], interactor_hash)
            else:
                # Generate a .ans if not already generated by earlier steps.
                if needed(".ans"):
                    # Run the solution if available.
                    if t.config.solution:
                        if not t.config.solution.run(bar, cwd).status:
                            return False
                        used_solution = True
                        changed_ans = True
                    else:
                        # Otherwise, it's a hard error.
                        bar.error(f"{ansfile.name} does not exist and was not generated.")
                        return False

            if used_solution:
                meta_yaml.solution_hash = solution_hash
            if changed_ans:
                meta_yaml.ans_out_validator_hashes = {}
                meta_yaml.visualizer_hash = {}
            if changed_ans or used_solution:
                meta_yaml.write()

            assert ansfile.is_file(), f"Failed to generate ans file: {ansfile}"
            return True

        def generate_visualization(testcase: Testcase, bar: ProgressBar) -> bool:
            nonlocal meta_yaml

            if testcase.root in config.INVALID_CASE_DIRECTORIES:
                return True
            if testcase.root == "testing_tool_test":
                return True
            if config.args.no_visualizer:
                return True

            # Generate visualization
            in_path = cwd / "testcase.in"
            ans_path = cwd / "testcase.ans"
            out_path = cwd / "testcase.out"
            assert in_path.is_file()
            assert ans_path.is_file()

            feedbackdir = in_path.with_suffix(".feedbackdir")
            image_files = [f"judgeimage{ext}" for ext in config.KNOWN_VISUALIZER_EXTENSIONS] + [
                f"teamimage{ext}" for ext in config.KNOWN_VISUALIZER_EXTENSIONS
            ]

            def use_feedback_image(feedbackdir: Path, source: str) -> None:
                for name in image_files:
                    path = feedbackdir / name
                    if path.exists():
                        ensure_symlink(in_path.with_suffix(path.suffix), path)
                        bar.log(f"Using {name} from {source} as visualization")
                        return

            visualizer: Optional[visualize.AnyVisualizer] = problem.visualizer(
                visualize.InputVisualizer
            )
            output_visualizer = problem.visualizer(visualize.OutputVisualizer)
            visualizer_args = testcase.get_test_case_yaml(bar).input_visualizer_args
            if output_visualizer is not None:
                if out_path.is_file() or problem.settings.ans_is_output:
                    if visualizer is None or out_path.is_file():
                        visualizer = output_visualizer
                        visualizer_args = testcase.get_test_case_yaml(bar).output_visualizer_args
                    if not out_path.is_file():
                        assert problem.settings.ans_is_output
                        out_path = ans_path

            if visualizer is None:
                for ext in config.KNOWN_VISUALIZER_EXTENSIONS:
                    in_path.with_suffix(ext).unlink(True)
                use_feedback_image(feedbackdir, "validator")
                return True

            visualizer_hash: dict[object, object] = {
                "visualizer_hash": visualizer.hash,
                "visualizer_args": visualizer_args,
            }

            if meta_yaml.visualizer_hash == visualizer_hash:
                return True

            for ext in config.KNOWN_VISUALIZER_EXTENSIONS:
                in_path.with_suffix(ext).unlink(True)

            if isinstance(visualizer, visualize.InputVisualizer):
                result = visualizer.run(in_path, ans_path, cwd, visualizer_args)
            else:
                feedbackcopy = in_path.with_suffix(".feedbackcopy")
                shutil.rmtree(feedbackcopy)

                def skip_images(src: str, content: list[str]) -> list[str]:
                    return [] if src != str(feedbackdir) else image_files

                shutil.copytree(feedbackdir, feedbackcopy, ignore=skip_images)

                result = visualizer.run(
                    in_path,
                    ans_path,
                    out_path if not problem.interactive else None,
                    feedbackcopy,
                    visualizer_args,
                )
                if result.status:
                    use_feedback_image(feedbackdir, "output_visualizer")

            if result.status == ExecStatus.TIMEOUT:
                bar.debug(f"{Style.RESET_ALL}-> {shorten_path(problem, cwd)}")
                bar.error(
                    f"{type(visualizer).visualizer_type.capitalize()} Visualizer TIMEOUT after {result.duration}s"
                )
            elif not result.status:
                bar.debug(f"{Style.RESET_ALL}-> {shorten_path(problem, cwd)}")
                bar.error(
                    f"{type(visualizer).visualizer_type.capitalize()} Visualizer crashed",
                    result.err,
                )

            if result.status and config.args.error and result.err:
                bar.log("stderr", result.err)

            if result.status:
                meta_yaml.visualizer_hash = visualizer_hash
                meta_yaml.write()

            # errors in the visualizer are not critical
            return True

        def generate_empty_interactive_sample_ans() -> bool:
            if not t.sample:
                return True
            if not problem.interactive and not problem.multi_pass:
                return True
            for ext in ["", ".statement", ".download"]:
                ans_ext_file = infile.with_suffix(f".ans{ext}")
                if ans_ext_file.exists():
                    return True
                if infile.with_suffix(f".in{ext}").exists():
                    ans_ext_file.write_text("")
                    return True
            return True

        def copy_generated() -> None:
            identical_exts = set()

            for ext in config.KNOWN_DATA_EXTENSIONS:
                source = infile.with_suffix(ext)
                target = target_infile.with_suffix(ext)

                if source.is_file():
                    generator_config.known_files.add(target)
                    if target.is_file():
                        if source.read_bytes() == target.read_bytes() and not target.is_symlink():
                            # identical -> skip
                            identical_exts.add(ext)
                        else:
                            # different -> overwrite
                            generator_config.remove(target)
                            shutil.copy(source, target, follow_symlinks=True)
                            bar.log(f"CHANGED: {target.name}")
                    else:
                        # new file -> copy it
                        shutil.copy(source, target, follow_symlinks=True)
                        bar.log(f"NEW: {target.name}")
                elif target.is_file():
                    if (
                        config.args.no_visualizer
                        and ext in config.KNOWN_VISUALIZER_EXTENSIONS
                        and ".in" in identical_exts
                        and ".ans" in identical_exts
                    ):
                        # When running with --no-visualizer and .in/.ans files did not change,
                        # do not remove output of visualizer.
                        # This is useful for when a user/CI has a clean cache (e.g. after a reboot).
                        # Also add target to known_files, so the cleanup step does not remove it.
                        generator_config.known_files.add(target)
                        continue
                    # Target exists but source wasn't generated -> remove it
                    generator_config.remove(target)
                    bar.log(f"REMOVED: {target.name}")
                else:
                    # both source and target do not exist
                    pass

        def add_test_case_to_cache() -> None:
            # Used to identify generated test cases
            generator_config.hashed_in.add(hash_file_content(infile))

            # Store the hashes of the generated files for this test case to detect duplicate test cases.
            hashes = {}

            # consider specific files for the uniqueness of this testcase
            relevant_files = {
                "testing_tool_test": [".in"],
                "invalid_input": [".in"],
                "invalid_answer": [".in", ".ans"],
                "invalid_output": [".in", ".ans", ".out"],
                "valid_output": [".in", ".ans", ".out"],
            }
            relevant_files_default = [".in"] if problem.settings.ans_is_output else [".in", ".ans"]
            extensions = relevant_files.get(t.root, relevant_files_default)

            for ext in extensions:
                if target_infile.with_suffix(ext).is_file():
                    hashes[ext] = hash_file_content(target_infile.with_suffix(ext))

            # combine hashes
            test_hash = combine_hashes_dict(hashes)

            # check for duplicates
            if test_hash not in generator_config.generated_test_cases:
                generator_config.generated_test_cases[test_hash] = t
            else:
                bar.warn(
                    f"Testcase {t.path} is equal to {generator_config.generated_test_cases[test_hash].path}."
                )

        # Step 1: handle non unique generate entry
        if t.copy_of is not None:
            if t.intended_copy:
                # This was generated by count: so we can simply link
                t.copy_of.link(problem, generator_config, bar, target_infile)
            else:
                # This is a duplicated rule, we copy to show this
                copy_generated()
            t.generate_success = True
            generator_config.failed -= 1
            generator_config.copied += 1
            bar.done(message="SKIPPED: up to date")
            return

        # Step 2: generate .in if needed (and possible other files)
        if not generate_from_rule():
            return

        if infile.is_file():
            # Step 3: check .in if needed
            testcase = Testcase(problem, infile, short_path=t.path / t.name)
            if not t.validate_in(problem, testcase, meta_yaml, bar):
                return

            # Step 3.1: check patterns
            check_match(testcase, "in", bar)

            # Step 4: generate .ans and .interaction if needed
            if not generate_from_solution(testcase, bar):
                return

            # Step 5: validate .ans (and .out if it exists)
            if not t.validate_ans_and_out(problem, testcase, meta_yaml, bar):
                return

            # Step 5.1: check patterns
            check_match(testcase, "ans", bar)

            # Step 6: generate visualization if needed
            if not generate_visualization(testcase, bar):
                return

        # Step 7: for interactive and/or multi-pass samples, generate empty .ans if it does not exist
        if not generate_empty_interactive_sample_ans():
            return

        # Step 8: copy all generated files
        copy_generated()

        # Note that we set this to true even if not all files were overwritten -- a different log/warning message will be displayed for that.
        t.generate_success = True
        generator_config.failed -= 1
        generator_config.generated += 1
        if infile.is_file():
            add_test_case_to_cache()
        if config.args.action != "generate":
            bar.logged = True  # Disable redundant 'up to date' message in run mode.
        bar.done(message="SKIPPED: up to date")


# Helper that has the required keys needed from a parent directory.
class RootDirectory:
    path = Path("")
    config = None
    numbered = False


class Directory(Rule):
    # Process yaml object for a directory.
    def __init__(
        self,
        problem: Problem,
        key: str,
        name: str,
        yaml: dict[object, object],
        parent: "AnyDirectory",
    ) -> None:
        assert is_directory(yaml)

        # The root Directory object has name ''.
        if not isinstance(parent, RootDirectory):
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(name):
                raise ParseException("Directory does not have a valid name.", parent.path / name)

        super().__init__(problem, key, name, yaml, parent)
        bar = PrintBar("generators.yaml", item=self.path)

        if isinstance(parent, RootDirectory):
            for any_key in yaml:
                if any_key in RESERVED_DIRECTORY_KEYS:
                    raise ParseException(
                        f"Directory must not contain reserved key {any_key}.", self.path
                    )
                if any_key in DEPRECATED_ROOT_KEYS:
                    bar.warn(f"Deprecated root level key: {any_key}, ignored")
                elif any_key not in [*KNOWN_DIRECTORY_KEYS, *KNOWN_ROOT_KEYS]:
                    if config.args.action == "generate":
                        bar.log(f"Unknown root level key: {any_key}")
        else:
            assert name != ""
            for any_key in yaml:
                if any_key in [*RESERVED_DIRECTORY_KEYS, *KNOWN_ROOT_KEYS]:
                    raise ParseException(
                        f"Directory must not contain reserved key {any_key}.", self.path
                    )
                if any_key not in KNOWN_DIRECTORY_KEYS:
                    if config.args.action == "generate":
                        bar.log(f"Unknown directory level key: {any_key}")

        self.test_group_yaml: object | Literal[False] = yaml.get("test_group.yaml", False)
        self.numbered = False

        # List of child TestcaseRule/Directory objects, filled by parse().
        self.data = list[TestcaseRule | Directory]()
        # Map of short_name => TestcaseRule, filled by parse().
        self.includes = dict[str, TestcaseRule]()

        # Sanity checks for possibly empty data.
        if "data" not in yaml:
            return
        data = yaml["data"]
        if data is None:
            return
        assert_type("Data", data, (dict, list))

        if isinstance(data, list):
            self.numbered = True
            if len(data) == 0:
                return

            for d in data:
                assert_type("Numbered case", d, dict)
                if len(d) != 1:
                    found_keys = [key for key in UNIQUE_TESTCASE_KEYS if key in d]
                    if found_keys:
                        raise ParseException(
                            f"Dictionary must contain exactly one named testcase/group.\nTo specify {'/'.join(found_keys)}, indent one more level.",
                            self.path,
                        )
                    else:
                        raise ParseException(
                            "Dictionary must contain exactly one named testcase/group.",
                            self.path,
                        )

    # The @overload definitions are purely here for static typing reasons.
    # This overload takes a single function as argument, which is used for both files and directories.
    @overload
    def walk(
        self,
        testcase_f: Optional[Callable[["TestcaseRule | Directory"], object]],
        *,
        skip_restricted: bool = True,
    ) -> None: ...

    # This overload takes one function for test cases and a separate function for directories.
    @overload
    def walk(
        self,
        testcase_f: Optional[Callable[[TestcaseRule], object]],
        dir_f: Optional[Callable[["Directory"], object]],
        *,
        skip_restricted: bool = True,
    ) -> None: ...

    # Map a function over all test cases directory tree.
    # dir_f by default reuses testcase_f
    def walk(
        self,
        testcase_f: Optional[
            Callable[["TestcaseRule | Directory"], object] | Callable[[TestcaseRule], object]
        ] = None,
        dir_f: (
            Literal[True]
            | Optional[
                Callable[["TestcaseRule | Directory"], object] | Callable[["Directory"], object]
            ]
        ) = True,
        *,
        skip_restricted: bool = True,
    ) -> None:
        if dir_f is True:
            dir_f = cast(Optional[Callable[["TestcaseRule | Directory"], object]], testcase_f)
        if dir_f:
            dir_f(self)

        for d in self.data:
            if isinstance(d, Directory):
                d.walk(testcase_f, dir_f)
            elif isinstance(d, TestcaseRule):
                if not d.process and skip_restricted:
                    continue
                if testcase_f:
                    testcase_f(d)
            else:
                assert False

    def generate(
        d, problem: Problem, generator_config: "GeneratorConfig", bar: ProgressBar
    ) -> None:
        # Generate the current directory:
        # - Create the directory.
        # - Write test_group.yaml.
        # - Link included testcases.
        #   - Input of included testcases are re-validated with the
        #     directory-specific input validator flags.
        bar.start(str(d.path))

        # Create the directory.
        dir_path = problem.path / "data" / d.path
        dir_path.mkdir(parents=True, exist_ok=True)

        # Write the test_group.yaml, or remove it when the key is set but empty.
        test_group_yaml_path = dir_path / "test_group.yaml"
        if d.test_group_yaml:
            generator_config.known_files.add(test_group_yaml_path)
            yaml_text = write_yaml(d.test_group_yaml)

            if test_group_yaml_path.is_file():
                if yaml_text == test_group_yaml_path.read_text():
                    # identical -> skip
                    pass
                else:
                    # different -> overwrite
                    generator_config.remove(test_group_yaml_path)
                    test_group_yaml_path.write_text(yaml_text)
                    bar.log("CHANGED: test_group.yaml")
            else:
                # new file -> create it
                test_group_yaml_path.write_text(yaml_text)
                bar.log("NEW: test_group.yaml")
        elif d.test_group_yaml is None and test_group_yaml_path.is_file():
            # empty -> remove it
            generator_config.remove(test_group_yaml_path)
            bar.log("REMOVED: test_group.yaml")
        bar.done()

    def generate_includes(
        d, problem: Problem, generator_config: "GeneratorConfig", bar: ProgressBar
    ) -> None:
        for key in d.includes:
            t = d.includes[key]
            target = t.path
            new_case = d.path / target.name

            if not generator_config.process_testcase(new_case):
                continue

            bar.start(str(new_case))
            generator_config.failed += 1
            infile = problem.path / "data" / target.parent / (target.name + ".in")
            ansfile = problem.path / "data" / target.parent / (target.name + ".ans")
            new_infile = problem.path / "data" / d.path / (target.name + ".in")

            if not t.process:
                bar.warn(f"Included case {target} was not processed.")
                bar.done()
                continue

            if not t.generate_success:
                bar.error(f"Included case {target} has errors.")
                bar.done()
                continue

            if not infile.is_file():
                bar.warn(f"{target}.in does not exist.")
                bar.done()
                continue

            if not ansfile.is_file():
                bar.warn(f"{target}.ans does not exist.")
                bar.done()
                continue

            # Check if the testcase was already validated.
            meta_yaml = TestcaseRule.MetaYaml(problem, t)
            testcase = Testcase(problem, infile, short_path=new_case)

            # Step 1: validate .in
            if not t.validate_in(problem, testcase, meta_yaml, bar):
                continue

            # Step 2: validate .ans (and .out if it exists)
            if not t.validate_ans_and_out(problem, testcase, meta_yaml, bar):
                continue

            t.link(problem, generator_config, bar, new_infile)
            generator_config.failed -= 1
            generator_config.included += 1
            bar.done()


# Returns the numbered name
def next_numbered_name(base_name: str, i: Iterator[int], n: int) -> Iterator[str]:
    width = len(str(n))
    while True:
        number_prefix = f"{next(i):0{width}}"
        if base_name:
            yield f"{number_prefix}-{base_name}"
        else:
            assert base_name is None or base_name == ""
            yield number_prefix


AnyDirectory = RootDirectory | Directory


class GeneratorConfig:
    @staticmethod
    def _parse_generators(generators_yaml: YAML_TYPE) -> dict[Path, list[Path]]:
        assert_type("Generators", generators_yaml, dict)
        assert isinstance(generators_yaml, dict)
        generators = {}
        for gen, deps in generators_yaml.items():
            if not isinstance(gen, str):
                raise ParseException("Invalid generator name", f"generators/{gen}")
            if (
                gen.startswith("/")
                or Path(gen).is_absolute()
                or not config.COMPILED_FILE_NAME_REGEX.fullmatch(gen + ".x")
            ):
                raise ParseException("Invalid generator name", f"generators/{gen}")

            path = Path("generators") / gen

            assert_type("Generator dependencies", deps, list)
            assert isinstance(deps, list)
            if len(deps) == 0:
                raise ParseException("Generator dependencies must not be empty.", path)
            for d in deps:
                assert_type("Generator dependencies", d, str)

            generators[path] = [Path("generators") / d for d in deps]
        return generators

    # Parse generators.yaml.
    def __init__(self, problem: Problem, restriction: Optional[Sequence[Path]] = None) -> None:
        self.problem = problem
        yaml_path = self.problem.path / "generators" / "generators.yaml"
        self.n_parse_error = 0

        # A map of paths `secret/test_group/test_case` to their canonical TestcaseRule.
        # For generated cases this is the rule itself.
        # For included cases, this is the 'resolved' location of the test case that is included.
        self.known_cases = dict[Path, TestcaseRule]()
        # A map of paths `secret/test_group` to Directory rules.
        self.known_directories = dict[Path, Directory]()
        # Used for cleanup
        self.known_files = set[Path]()
        # A map from key to (is_included, list of test cases and directories),
        # used for `include` statements.
        self.known_keys = collections.defaultdict[str, tuple[bool, list[TestcaseRule | Directory]]](
            lambda: (False, [])
        )
        # A set of testcase rules, including seeds.
        self.rules_cache = dict[str, TestcaseRule]()
        # The set of generated test cases keyed by hash(test_case).
        self.generated_test_cases = dict[str, TestcaseRule]()
        # Path to the trash directory for this run
        self.trash_dir: Optional[Path] = None
        # Set of hash(.in) for all generated testcases
        self.hashed_in = set[str]()
        # Files that should be processed
        self.restriction = restriction
        # replaced during parse_yaml
        self.generators = dict[Path, list[Path]]()

        # stats
        self.failed = 0
        self.generated = 0
        self.included = 0
        self.copied = 0

        if yaml_path.is_file():
            self.yaml = read_yaml(yaml_path)
            self.has_yaml = True
        else:
            self.yaml = None
            self.has_yaml = False

        try:
            self.parse_yaml(self.yaml)
        except ParseException as e:
            # Handle fatal parse errors
            PrintBar("generators.yaml", item=e.path).fatal(e.message or "")

    # testcase_short_path: secret/1.in
    def process_testcase(self, relative_testcase_path: Path) -> bool:
        if not self.restriction:
            return True
        absolute_testcase_path = self.problem.path / "data" / relative_testcase_path.with_suffix("")
        for p in self.restriction:
            for basedir in get_basedirs(self.problem, "data"):
                if is_relative_to(basedir / p, absolute_testcase_path):
                    return True
        return False

    def parse_yaml(self, yaml: object) -> None:
        assert_type("Root yaml", yaml, (type(None), dict))
        if yaml is None:
            yaml = dict()
        assert isinstance(yaml, dict)

        # Read root level configuration
        if "generators" in yaml:
            self.generators = self._parse_generators(yaml["generators"])

        def add_known(obj: TestcaseRule | Directory) -> None:
            path = obj.path
            name = path.name
            if isinstance(obj, TestcaseRule):
                self.known_cases[path] = obj
            elif isinstance(obj, Directory):
                self.known_directories[path] = obj
            else:
                assert False

            is_included, cases_list = self.known_keys[obj.key]
            cases_list.append(obj)
            if is_included and len(cases_list) == 2:
                PrintBar("generators.yaml", item=obj.path).error(
                    f"Included key {name} exists more than once as {cases_list[0].path} and {cases_list[1].path}."
                )

        num_numbered_test_cases = 0
        next_test_case_id = itertools.count(1)

        def parse_count(yaml: YAML_TYPE) -> list[int]:
            """Raises:
            ParseException: on invalid count specification. Since we can't determine
            the correct numbering of subsequent test cases, we have to abort parsing.
            """
            if not has_count(yaml):
                return [1]
            assert isinstance(yaml, dict)
            lineno = yaml.lc.line if hasattr(yaml, "lc") else "unknown line"
            match yaml["count"]:
                case int(count):
                    if not 1 <= count <= 100:
                        raise ParseException(
                            f"{lineno}: Invalid count {count}; must be between 1 and 100."
                        )
                    count_list = list(range(1, count + 1))
                case list(items):
                    seen = set()
                    for item in items:
                        if not isinstance(item, int):
                            raise ParseException(
                                f"{lineno}: Invalid count list; found {item} but expected int."
                            )
                        if item in seen:
                            raise ParseException(
                                f"{lineno}: Invalid count list; duplicate element {item}."
                            )
                        seen.add(item)
                    count_list = items
                case str(s):
                    if m := INCLUSIVE_RANGE_REGEX.match(s):
                        lo, hi = int(m[1]), int(m[2])
                        if lo > hi:
                            raise ParseException(
                                f"{lineno}: Empty count range, start={lo} must be <= end={hi}."
                            )
                        if hi - lo + 1 > 100:
                            raise ParseException(
                                f"{lineno}: Count range too large, length {hi - lo + 1} > 100."
                            )
                    else:
                        raise ParseException(
                            f"{lineno}: Invalid count expression {s}; expected format is '-4..=5'."
                        )
                    count_list = list(range(lo, hi + 1))
                case _:
                    assert False  # has_count already checked for int | list | str
            assert 1 <= len(count_list) <= 100
            return count_list

        # Count the number of testcases in the given directory yaml.
        # This parser is quite forgiving,
        def count(yaml: YAML_TYPE) -> None:
            nonlocal num_numbered_test_cases
            if not isinstance(yaml, dict):
                return
            ds = yaml.get("data")
            if isinstance(ds, dict):
                ds = [ds]
                numbered = False
            else:
                numbered = True
            if not isinstance(ds, list):
                return
            for elem in ds:
                if isinstance(elem, dict):
                    for key in elem:
                        if is_testcase(elem[key]) and numbered:
                            num_numbered_test_cases += len(parse_count(elem[key]))
                        elif is_directory(elem[key]):
                            count(elem[key])

        count(yaml)

        # Main recursive parsing function.
        # key: the yaml key e.g. 'testcase'
        # name_gen: each call should result in the next (possibly numbered) name e.g. '01-testcase'
        # Returns either a single Rule or a list of Rules
        def parse(
            key: str, name_gen: Iterator[str], yaml: YAML_TYPE, parent: AnyDirectory
        ) -> Directory | list[TestcaseRule]:
            name = next(name_gen)
            assert_type("Testcase/directory", yaml, (type(None), str, dict), parent.path)
            if not is_testcase(yaml) and not is_directory(yaml):
                raise ParseException("not parsed as a testcase or directory.", parent.path / name)

            if is_testcase(yaml):
                if isinstance(parent, RootDirectory):
                    raise ParseException("Test case must be inside a Directory.", name)

                count_list = parse_count(yaml)
                # pad numbers with leading zeros if counts are consecutive
                is_consecutive = max(count_list) - min(count_list) == len(count_list) - 1
                padding = max(len(str(v)) for v in count_list) if is_consecutive else 0

                ts: list[TestcaseRule] = []
                for i, count_value in enumerate(count_list):
                    if i > 0:  # need a fresh name in every round but the first
                        name = next(name_gen)
                    if has_count(yaml):
                        name += f"-{count_value:0{padding}}"

                    t = TestcaseRule(self.problem, self, key, name, yaml, parent, count_value)
                    if t.path in self.known_cases:
                        PrintBar("generators.yaml", item=t.path).error(
                            "was already parsed. Skipping."
                        )
                        continue

                    add_known(t)
                    ts.append(t)
                return ts

            assert is_directory(yaml)
            assert isinstance(yaml, dict)

            d = Directory(self.problem, key, name, yaml, parent)
            if d.path in self.known_cases or d.path in self.known_directories:
                raise ParseException("Duplicate entry", d.path)
            add_known(d)

            # Parse child test cases/groups.
            if "data" in yaml and yaml["data"]:
                data = yaml["data"] if isinstance(yaml["data"], list) else [yaml["data"]]
                # Count the number of child test groups.
                num_test_groups = 0
                for dictionary in data:
                    assert_type("Elements of data", dictionary, dict, d.path)
                    for key in dictionary.keys():
                        assert_type("Key of data", key, (type(None), str), d.path / str(key))
                    for _, child_yaml in sorted(dictionary.items()):
                        if is_directory(child_yaml):
                            num_test_groups += 1

                next_test_group_id = itertools.count(1)
                for dictionary in data:
                    for key in dictionary:
                        assert_type("Test case/group name", key, (type(None), str), d.path)

                    # Process named children alphabetically, but not in the root directory.
                    # There, process in the 'natural order'.
                    order = [
                        "sample",
                        "secret",
                        "invalid_output",
                        "invalid_answer",
                        "invalid_input",
                        "valid_output",
                    ]
                    keys = dictionary.keys()
                    if isinstance(parent, RootDirectory):
                        keys = sorted(
                            keys,
                            key=lambda k: ((order.index(k), k) if k in order else (999, k)),
                        )
                        deprecated = [
                            "invalid_outputs",
                            "invalid_answers",
                            "invalid_inputs",
                            "valid_outputs",
                        ]
                        for key in deprecated:
                            if key in keys:
                                warn(
                                    f"Found key data.{key} in generators.yaml, should be: data.{key[:-1]} (singular form)."
                                )
                    else:
                        keys = sorted(keys)

                    for child_key in keys:
                        child_yaml = dictionary[child_key]
                        if d.numbered:
                            if is_directory(child_yaml):
                                child_name = next_numbered_name(
                                    child_key, next_test_group_id, num_test_groups
                                )
                            elif is_testcase(child_yaml):
                                child_name = next_numbered_name(
                                    child_key,
                                    next_test_case_id,
                                    num_numbered_test_cases,
                                )
                            else:
                                # Use error will be given inside parse(child).
                                child_name = itertools.repeat("")

                        else:
                            assert isinstance(child_key, str)
                            child_name = itertools.repeat(child_key)
                            if not next(child_name):
                                raise ParseException(
                                    "Unnumbered test cases must not have an empty key",
                                    d.path,
                                )
                        c = parse(child_key, child_name, child_yaml, d)
                        if isinstance(c, list):
                            d.data.extend(c)
                        elif c is not None:
                            d.data.append(c)

            # Include TestcaseRule t for the current directory.
            def add_included_case(t: TestcaseRule) -> None:
                target = t.path
                name = target.name
                p = d.path / name
                if p in self.known_cases:
                    bar = PrintBar("generators.yaml", item=p)
                    if target != self.known_cases[p].path:
                        if self.known_cases[p].path == p:
                            bar.error(f"conflict with included case {target}.")
                        else:
                            bar.error(
                                f"included with multiple targets {target} and {self.known_cases[p].path}."
                            )
                    return
                self.known_cases[p] = t
                d.includes[name] = t

            if "include" in yaml:
                includes = yaml["include"]
                assert_type("includes", includes, list, d.path)
                assert isinstance(includes, list)

                bar = PrintBar("generators.yaml", item=d.path)
                for include in includes:
                    assert_type("include", include, str, d.path)
                    if "/" in include:
                        bar.error(f"Include {include} should be a test case/group key, not a path.")
                        continue

                    if include in self.known_keys:
                        is_included, cases_list = self.known_keys[include]
                        if len(cases_list) != 1:
                            bar.error(f"Included key {include} exists more than once.")
                            continue

                        self.known_keys[include] = (True, cases_list)
                        obj = cases_list[0]
                        if isinstance(obj, TestcaseRule):
                            add_included_case(obj)
                        else:
                            obj.walk(
                                add_included_case,
                                lambda d: list(map(add_included_case, d.includes.values())),
                                skip_restricted=False,
                            )
                            pass
                    else:
                        bar.error(
                            f"Unknown include key {include} does not refer to a previous test case."
                        )
                        continue
            return d

        root_dir = parse("", itertools.repeat(""), yaml, RootDirectory())
        assert isinstance(root_dir, Directory)
        self.root_dir = root_dir

    def build(
        self, build_visualizers: bool = True, skip_double_build_warning: bool = False
    ) -> None:
        generators_used: set[Path] = set()
        solutions_used: set[Path] = set()

        # Collect all programs that need building.
        # Also, set the default submission if needed.
        # We only do this now to prevent instantiating
        # the default solution when it's not actually needed.
        default_solution: Optional[SolutionInvocation] = None

        def collect_programs(t: TestcaseRule) -> None:
            if isinstance(t, TestcaseRule):
                if t.generator:
                    generators_used.add(t.generator.program_path)
            if config.args.no_solution:
                t.config.solution = None
            elif t.config.needs_default_solution:
                # Initialize the default solution if needed.
                nonlocal default_solution
                if default_solution is None:
                    default_path = default_solution_path(self)
                    default_solution = SolutionInvocation(self.problem, str(default_path))
                t.config.solution = default_solution
            if t.config.solution:
                solutions_used.add(t.config.solution.program_path)

        self.root_dir.walk(collect_programs, dir_f=None)

        def build_programs(
            program_type: type[program.Generator | run.Submission],
            program_paths: Iterable[Path],
        ) -> None:
            programs = list[program.Generator | run.Submission]()
            for program_path in program_paths:
                path = self.problem.path / program_path
                if program_type is program.Generator and program_path in self.generators:
                    deps = [Path(self.problem.path) / d for d in self.generators[program_path]]
                    programs.append(program.Generator(self.problem, path, deps=deps))
                else:
                    if program_type is run.Submission:
                        programs.append(
                            run.Submission(self.problem, path, skip_double_build_warning=True)
                        )
                    else:
                        programs.append(
                            program_type(
                                self.problem,
                                path,
                                skip_double_build_warning=skip_double_build_warning,
                            )
                        )

            bar = ProgressBar(f"Build {program_type.__name__.lower()}s", items=programs)

            def build_program(p: program.Generator | run.Submission) -> None:
                localbar = bar.start(p)
                p.build(localbar)
                localbar.done()

            parallel.run_tasks(build_program, programs)

            bar.finalize(print_done=False)

        # TODO: Consider building all types of programs in parallel as well.
        build_programs(program.Generator, generators_used)
        build_programs(run.Submission, solutions_used)
        if build_visualizers:
            self.problem.visualizer(visualize.InputVisualizer)
            self.problem.visualizer(visualize.OutputVisualizer)

        self.problem.validators(validate.InputValidator)
        self.problem.validators(validate.AnswerValidator)
        self.problem.validators(validate.OutputValidator)

        def cleanup_build_failures(t: TestcaseRule) -> None:
            if t.config.solution and t.config.solution.program is None:
                t.config.solution = None

        self.root_dir.walk(cleanup_build_failures, dir_f=None)

    def run(self) -> None:
        self.update_gitignore_file()
        self.problem.reset_testcase_hashes()

        item_names = []
        self.root_dir.walk(lambda x: item_names.append(x.path))

        def count_dir(d: Directory) -> None:
            for name in d.includes:
                item_names.append(d.path / name)

        self.root_dir.walk(None, count_dir)
        bar = ProgressBar("Generate", items=item_names)

        # Testcases are generated in two steps:
        # 1. Generate directories and unique testcases listed in generators.yaml.
        # 2. Generate duplicates of known testcases. All directories should already exists
        #    Each directory is only started after previous directories have
        #    finished and handled by the main thread, to avoid problems with
        #    included testcases.

        # 1
        def runner(t: TestcaseRule) -> None:
            if t.copy_of is None:
                t.generate(self.problem, self, bar)

        p = parallel.new_queue(runner)

        def generate_dir(d: Directory) -> None:
            p.join()
            d.generate(self.problem, self, bar)

        self.root_dir.walk(p.put, generate_dir)
        p.done()

        # 2
        def runner_copies(t: TestcaseRule) -> None:
            if t.copy_of is not None:
                t.generate(self.problem, self, bar)

        p = parallel.new_queue(runner_copies)

        def generate_includes(d: Directory) -> None:
            p.join()
            d.generate_includes(self.problem, self, bar)

        self.root_dir.walk(p.put, generate_includes)
        p.done()

        stats = []
        if self.failed > 0:
            stats.append(f"{Fore.RED}{self.failed} failed{Style.RESET_ALL}, ")
        total = self.generated + self.included + self.copied
        plurals = "s" if total != 1 else ""
        stats.append(f"{total} case{plurals} generated")
        if len(self.generated_test_cases) != total:
            stats.append(
                f" {Fore.YELLOW}(unique: {len(self.generated_test_cases)}){Style.RESET_ALL}"
            )
        bar.item_width = 0
        bar.finalize(message="".join(stats))

    # move a file or into the trash directory
    def remove(self, src: Path) -> None:
        if self.trash_dir is None:
            self.trash_dir = self.problem.tmpdir / "trash" / secrets.token_hex(4)
        dst = self.trash_dir / src.absolute().relative_to((self.problem.path / "data").absolute())
        dst.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(src, dst)

    def _remove_unknown(self, path: Path, bar: ProgressBar, silent: bool = False) -> None:
        local = path.relative_to(self.problem.path / "data")
        keep = any(
            (
                path.is_dir() and local in self.known_directories,
                not path.is_dir() and path in self.known_files,
                not path.is_dir() and not self.process_testcase(local),
            )
        )
        if keep:
            if path.is_dir():
                # specially handle known .in files to reduce output noice
                for f in sorted(path.glob("*.in")):
                    if f.is_file() and hash_file_content(f) in self.hashed_in:
                        for ext in config.KNOWN_TEXT_DATA_EXTENSIONS:
                            tmp = f.with_suffix(ext)
                            if tmp.is_file():
                                self._remove_unknown(f.with_suffix(ext), bar, True)
                for f in sorted(path.glob("*")):
                    self._remove_unknown(f, bar)
        else:
            self.remove(path)
            if silent:
                bar.debug(f"REMOVED: {path.name}")
            else:
                bar.log(f"REMOVED: {path.name}")

    # remove all files in data that were not written by the during run
    def clean_up(self) -> None:
        bar = ProgressBar("Clean Up", max_len=-1)

        self._remove_unknown(self.problem.path / "data", bar)
        if self.trash_dir is not None:
            bar.warn("Some files were changed/removed.", f"-> {self.trash_dir}")
        bar.finalize()

    # write a gitignore file to ignore everything in data/ except data/sample/
    def update_gitignore_file(self) -> None:
        gitignorefile = self.problem.path / ".gitignore"

        content = """#GENERATED BY BAPCtools
data/*
!data/sample/
"""

        if gitignorefile.is_file():
            # if there is any rule for data/ we expect that the user knows
            # what he does.
            if "data/" not in gitignorefile.read_text():
                with gitignorefile.open("a") as f:
                    f.write("\n")
                    f.write(content)
                log("Updated .gitignore.")
        else:
            assert not gitignorefile.exists()
            gitignorefile.write_text(content)
            log("Created .gitignore.")

    # add all testcases specified as copy keys in the generators.yaml
    # can handle files and complete directories
    def add(self, to_add: Sequence[Path]) -> bool:
        if self.n_parse_error > 0:
            return False

        in_files = []
        for path in to_add:
            if path.suffix == ".in":
                in_files.append(path)
            else:
                in_files += [
                    test.relative_to(self.problem.path)
                    for test in (self.problem.path / path).glob("*.in")
                ]

        known = {
            rule.copy.relative_to(self.problem.path)
            for rule in self.known_cases.values()
            if rule.copy is not None and rule.copy.is_relative_to(self.problem.path)
        }

        generators_yaml = self.problem.path / "generators" / "generators.yaml"
        data = read_yaml(generators_yaml)
        if data is None:
            data = CommentedMap()
        assert isinstance(data, CommentedMap)

        parent = ryaml_get_or_add(data, "data")
        parent = ryaml_get_or_add(parent, "secret")
        entry = ryaml_get_or_add(parent, "data", CommentedSeq)

        bar = ProgressBar("Adding", items=in_files)
        for in_file in sorted(in_files, key=lambda x: x.name):
            bar.start(str(in_file))
            if not (self.problem.path / in_file).exists():
                bar.warn("file not found. Skipping.")
            elif in_file in known:
                bar.log("already found in generators.yaml. Skipping.")
            else:
                entry.append(CommentedMap())
                path_in_gen = in_file.relative_to("generators")
                name = path_in_gen.with_suffix("").as_posix().replace("/", "_")
                new = CommentedMap({"copy": path_in_gen.with_suffix("").as_posix()})
                new.fa.set_flow_style()
                entry[-1][str(name)] = new
                bar.log("added to generators.yaml.")
            bar.done()

        if len(parent["data"]) == 0:
            parent["data"] = None

        write_yaml(data, generators_yaml)
        bar.finalize()
        return True

    # reorder all testcases in the given directories
    def reorder(self) -> bool:
        if self.n_parse_error > 0:
            return False

        directory_rules = set()
        assert config.args.testcases is not None  # set in cli.py
        for t in config.args.testcases:
            path = t.relative_to("data")
            parts = path.parts
            if not parts:
                warn("Cannot reorder Root directory. Skipping.")
            elif parts[0] in config.INVALID_CASE_DIRECTORIES:
                warn(f"{t} is used for invalid test data. Skipping.")
            elif parts[0] == "valid_output":
                warn(f"{t} is used for valid test data. Skipping.")
            elif parts[0] == "testing_tool_test":
                warn(f"{t} is used to test the testing tool. Skipping.")
            elif path not in self.known_directories:
                warn(f"{t} is not a generated directory. Skipping.")
            elif not self.known_directories[path].numbered:
                warn(f"{t} is not numbered. Skipping.")
            elif not self.known_directories[path].data:
                warn(f"{t} is empty. Skipping.")
            else:
                directory_rules.add(self.known_directories[path])

        data = self.problem.path / "data"

        testcase_filter = set()
        for d in directory_rules:
            for c in d.data:
                testcase_filter.add(data / c.path.with_suffix(".in"))

        ts_pair = self.problem.prepare_run()
        if not ts_pair:
            return False

        testcases = [t for t in ts_pair[0] if t.in_path in testcase_filter]
        submissions = [s for s in ts_pair[1] if s.expected_verdicts != [Verdict.ACCEPTED]]

        if not testcases:
            error("No testcases found.")
            return False
        if not submissions:
            error("No rejected submissions found.")
            return False

        ok, verdict_table = Problem.run_some(testcases, submissions)
        # ok == False only indicates that some submission did not Fail
        # if not ok:
        #     return False
        # verdict_table.print(new_lines=1)

        testcase_paths = {t.in_path.relative_to(data).with_suffix("") for t in testcases}
        max_testcase_len = max([len(str(t)) for t in testcase_paths])
        for d in directory_rules:
            eprint()
            eprint(f"{Fore.CYAN}Reorder{Style.RESET_ALL}: {d.path}")

            # directory must be numbered
            assert isinstance(d.yaml, dict)
            assert "data" in d.yaml
            assert isinstance(d.yaml["data"], list)

            # don't move unknown test cases/groups, or test cases with count
            test_nodes = {
                id(c.yaml): str(c.path)
                for c in d.data
                if c.path in testcase_paths and not has_count(c.yaml)
            }
            others = [e for e in d.yaml["data"] if id(next(iter(e.values()))) not in test_nodes]

            class TestcaseResult:
                def __init__(self, yaml: dict[object, object]) -> None:
                    self.yaml = yaml
                    self.name = test_nodes[id(next(iter(yaml.values())))]
                    self.scores = []
                    self.result = []
                    for i in range(len(submissions)):
                        verdict = verdict_table.results[i][self.name]
                        # moving TLE cases to the front is most important to save resources
                        # RTE are less reliable and therefore less important than WA
                        if verdict == Verdict.TIME_LIMIT_EXCEEDED:
                            self.scores.append((i, 8))
                        elif verdict == Verdict.WRONG_ANSWER:
                            self.scores.append((i, 4))
                        elif verdict == Verdict.RUNTIME_ERROR:
                            self.scores.append((i, 3))
                        self.result.append(verdict_table._get_verdict(i, self.name))

                def __str__(self) -> str:
                    return f"{Fore.CYAN}Reorder{Style.RESET_ALL}: {self.name:<{max_testcase_len}} {''.join(self.result)}"

                def score(self, weights: list[int]) -> int:
                    return sum(weights[i] * x for i, x in self.scores)

                def update(self, weights: list[int]) -> list[int]:
                    # the weights for each submission that did not fail on this testcase get doubled
                    # up to a limit of 2**16. (The same as halving the weight of all submission that failed)
                    weights = [x * 2 for x in weights]
                    even = True
                    for i, _ in self.scores:
                        weights[i] //= 2
                        even &= weights[i] % 2 == 0
                    if even:
                        weights = [x // 2 for x in weights]
                    else:
                        weights = [min(2**16, x) for x in weights]
                    return weights

            todo = [
                TestcaseResult(e)
                for e in d.yaml["data"]
                if id(next(iter(e.values()))) in test_nodes
            ]

            # Each submission is initially assigned a weight of one. The weight contributes to the score of a testcase if
            # the submission fails on this testcase. If a testcase is selected the weights for each submission that it fails
            # get halved (or all other get doubled) to encourage making the remaining submissions fail. We greedily pick the
            # submission that has the heighest score. Note that we additionally consider the type of failing (WA/TLE/RTE)
            # see class TestcaseResult.
            # Worstcase runtime testcases^2 * submissions
            bar = ProgressBar("Reorder", items=todo)
            done = []
            weights = [1] * len(submissions)
            while todo:
                scores = [t.score(weights) for t in todo]
                score = max(scores)
                if score == 0:
                    break
                index = scores.index(score)
                result = todo.pop(index)
                localbar = bar.start(result)
                done.append(result.yaml)
                weights = result.update(weights)
                localbar.log("moved to front")
                localbar.done()

            for _ in todo:
                bar.skip()
            bar.finalize()

            # move all unknown subgroups/testcases to the end (keeping their relative order)
            d.yaml["data"].clear()
            d.yaml["data"] += done + [t.yaml for t in todo] + others

        generators_yaml = self.problem.path / "generators" / "generators.yaml"
        write_yaml(self.yaml, generators_yaml)

        # regenerate cases
        eprint()
        new_config = GeneratorConfig(self.problem, config.args.testcases)
        new_config.build(skip_double_build_warning=True)
        new_config.run()
        new_config.clean_up()
        return new_config.n_parse_error == 0


# Delete files in the tmpdir trash directory. By default all files older than 10min are removed
# and additionally the oldest files are removed until the trash is less than 1 GiB
def clean_trash(problem: Problem, time_limit: int = 10 * 60, size_lim: int = 1024**3) -> None:
    trashdir = problem.tmpdir / "trash"
    if trashdir.exists():
        dirs = [(d, path_size(d)) for d in trashdir.iterdir()]
        dirs.sort(key=lambda d: d[0].stat().st_mtime)
        total_size = sum(x for d, x in dirs)
        begin = time.time() - time_limit
        for d, x in dirs:
            if x == 0 or total_size > size_lim or d.stat().st_mtime < begin:
                total_size -= x
                shutil.rmtree(d)


# Clean data/ and tmpdir/data/
def clean_data(problem: Problem, data: bool = True, cache: bool = True) -> None:
    dirs = [
        problem.path / "data" if data else None,
        problem.tmpdir / "data" if cache else None,
    ]
    for d in dirs:
        if d is not None and d.exists():
            shutil.rmtree(d)


def generate(problem: Problem) -> bool:
    clean_trash(problem)

    if config.args.clean:
        clean_data(problem, True, True)
        return True

    gen_config = GeneratorConfig(problem, config.args.testcases)

    if config.args.add is not None:
        return gen_config.add(config.args.add)

    if config.args.action == "generate":
        if not gen_config.has_yaml:
            error("Did not find generators/generators.yaml")
            return False

    if gen_config.has_yaml:
        gen_config.build()
        gen_config.run()
        gen_config.clean_up()

    if config.args.reorder:
        return gen_config.reorder()

    return True


def testcases(problem: Problem) -> set[Path]:
    gen_config = GeneratorConfig(problem)
    if gen_config.has_yaml:
        return {
            problem.path / "data" / p.parent / (p.name + ".in")
            for p, x in gen_config.known_cases.items()
            if x.parse_error is None
        }
    else:
        return {t for t in problem.path.glob("data/**/*.in") if not t.is_symlink()}
