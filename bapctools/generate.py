import collections
import difflib
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
from typing_extensions import TypeIs

from bapctools import config, parallel, program, run, validate, visualize
from bapctools.problem import Problem
from bapctools.testcase import Testcase
from bapctools.util import (
    BAR_TYPE,
    combine_hashes,
    combine_hashes_dict,
    ensure_symlink,
    eprint,
    error,
    ExecResult,
    ExecStatus,
    get_basedirs,
    hash_file_content,
    hash_string,
    log,
    path_size,
    PrintBar,
    ProgressBar,
    read_yaml,
    remove_path,
    ryaml_get_or_add,
    shorten_path,
    substitute,
    warn,
    write_yaml,
    YamlParser,
)
from bapctools.verdicts import Verdict

YAML_TYPE = Optional[str | dict[object, object]]


class ParseException(Exception):
    def __init__(self, message: str, path: Optional[Path | str] = None) -> None:
        super().__init__(message, path)
        self.message = message
        self.path = path


T = TypeVar("T")


def is_type(
    obj: object,
    t: type[T],
    name: str,
    path: Optional[Path] = None,
) -> TypeIs[T]:
    if isinstance(obj, t):
        return True
    raise ParseException(
        f"{name} must be of type {t.__name__}, found {obj.__class__.__name__}: {obj}",
        path,
    )


def is_list_type(
    obj: object,
    t: type[T],
    name: str,
    path: Optional[Path] = None,
) -> TypeIs[list[T]]:
    assert is_type(obj, list, name, path)
    for i, entry in enumerate(obj):
        assert is_type(entry, t, f"{name}[{i}]", path)
    return True


UNIQUE_TESTCASE_KEYS: Final[Sequence[str]] = (
    "copy",
    "generate",
    "count",
    "match",
    *(e[1:] for e in config.KNOWN_TEXT_DATA_EXTENSIONS),
)


def is_test_case(yaml: object) -> TypeIs[YAML_TYPE]:
    return (
        yaml is None
        or isinstance(yaml, str)
        or (isinstance(yaml, dict) and any(key in yaml for key in UNIQUE_TESTCASE_KEYS))
    )


def is_directory(yaml: object) -> TypeIs[dict[object, object]]:
    return isinstance(yaml, dict) and not is_test_case(yaml)


def has_count(yaml: object) -> TypeIs[dict[object, object]]:
    return (
        isinstance(yaml, dict) and "count" in yaml and isinstance(yaml["count"], (int, list, str))
    )


INCLUSIVE_RANGE_REGEX: Final[re.Pattern[str]] = re.compile(r"^(-?\d+)\.\.=(-?\d+)$")


def parse_count(yaml: YAML_TYPE) -> list[int]:
    """Raises:
    ParseException: on invalid count specification. Since we can't determine
    the correct numbering of subsequent test cases, we have to abort parsing.
    """
    if not has_count(yaml):
        return [1]
    lineno = f"{yaml.lc.line}: " if hasattr(yaml, "lc") else ""
    match yaml["count"]:
        case int(count):
            if not 1 <= count <= 100:
                raise ParseException(f"{lineno}Invalid count {count}; must be between 1 and 100.")
            count_list = list(range(1, count + 1))
        case list(items):
            seen = set()
            for item in items:
                if not isinstance(item, int):
                    raise ParseException(
                        f"{lineno}Invalid count list; found {item} but expected int."
                    )
                if item in seen:
                    raise ParseException(f"{lineno}Invalid count list; duplicate element {item}.")
                seen.add(item)
            count_list = items
        case str(s):
            if m := INCLUSIVE_RANGE_REGEX.match(s):
                lo, hi = int(m[1]), int(m[2])
                if lo > hi:
                    raise ParseException(
                        f"{lineno}Invalid count range, start={lo} must be <= end={hi}."
                    )
                if hi - lo + 1 > 100:
                    raise ParseException(
                        f"{lineno}Count range too large, length {hi - lo + 1} > 100."
                    )
            else:
                raise ParseException(
                    f"{lineno}Invalid count expression {s}; expected format is '-4..=5'."
                )
            count_list = list(range(lo, hi + 1))
        case _:
            assert False  # has_count already checked for int | list | str
    assert 1 <= len(count_list) <= 100
    return count_list


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


def is_local_symlink(file: Path) -> bool:
    if not file.is_symlink():
        return False
    dest = file.readlink()
    if dest.parent != Path():
        return False
    if file.name.split(".", 1)[0] != dest.name.split(".", 1)[0]:
        return False
    if "".join(file.suffixes) not in config.KNOWN_DATA_EXTENSIONS:
        return False
    return True


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
        allow_args: bool = True,
    ) -> None:
        self.problem = problem
        self.command_string = string

        commands = shlex.split(string)
        command = commands[0]
        self.args = commands[1:]
        if not allow_args and self.args:
            raise ParseException(f"{command} must not be invoked with arguments")

        # The name of the program to be executed, relative to the problem root.
        self.program_path = resolve_path(
            command, allow_absolute=allow_absolute, allow_relative=allow_relative
        )

        # Make sure that {seed} occurs at most once.
        seed_cnt = 0
        for arg in self.args:
            seed_cnt += len(self.SEED_REGEX.findall(arg))
        if seed_cnt > 1:
            raise ParseException("{seed(:[0-9]+)} may appear at most once.")

        # NOTE: This is also used by `fuzz`.
        self.uses_seed = seed_cnt > 0

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
        super().__init__(
            problem, string, allow_absolute=True, allow_relative=False, allow_args=False
        )

    # Run the submission, reading testcase.in from stdin and piping stdout to testcase.ans.
    # If the .ans already exists, nothing is done
    def run(self, bar: ProgressBar, cwd: Path) -> ExecResult:
        assert isinstance(self.program, run.Submission), "Submission program must be built!"

        in_path = cwd / "testcase.in"
        ans_path = cwd / "testcase.ans"

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        result = self.program.run(in_path, ans_path, cwd=cwd, generator_timeout=True)

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

        test_case = Testcase(self.problem, in_path, short_path=(t.path.parent / (t.name + ".in")))
        assert isinstance(self.program, run.Submission)
        r = run.Run(self.problem, self.program, test_case)

        # No {name}/{seed} substitution is done since all IO should be via stdin/stdout.
        result = r.run(bar, interaction=interaction_path)
        if result.verdict != Verdict.ACCEPTED:
            bar.error(f"could not generate .interaction, submission got {result.verdict}")
            return False

        return True


# Return absolute path to default submission, starting from the submissions directory.
# This function will always print a message.
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
        solutions = [s for s in problem.raw_submissions() if s.expectations.is_accepted()]
        if len(solutions) == 0:
            bar.fatal("No solution specified and no accepted submissions found.")

        # always try to take the same solution to not mess with hashing
        if stored_solution.is_file():
            old_solution = Path(stored_solution.read_text().strip())
            if any(old_solution == s.path for s in solutions):
                solution = old_solution

        if solution is None:
            # prefer solutions which are marked as model_solution
            if any(s.expectations.model_solution for s in solutions):
                solutions = [s for s in solutions if s.expectations.model_solution]
            solution = random.choice(solutions).path

        solution_short_path = solution.relative_to(problem.path / "submissions")

        if generator_config.has_yaml:
            if not isinstance(generator_config.yaml, dict) or "solution" in generator_config.yaml:
                bar.warn(
                    f"No solution specified. {solution_short_path} could not be added to generators.yaml"
                )
            else:
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
    stored_solution.write_text(solution.as_posix())
    return Path("/") / solution.relative_to(problem.path)


UNIQUE_DIRECTORY_KEYS: Final[Sequence[str]] = ("data", "test_group.yaml", "include")
ALLOWED_LINK_KEYS: Final[Sequence[str]] = (
    "in.statement",
    "ans.statement",
    "in.download",
    "ans.download",
)
ALLOWED_LINK_VALUES: Final[Sequence[str]] = (
    *ALLOWED_LINK_KEYS,
    "in",
    "ans",
)
RESERVED_DIRECTORY_KEYS: Final[Sequence[str]] = ("command",)
KNOWN_ROOT_KEYS: Final[Sequence[str]] = ("generators", "version")
DEPRECATED_ROOT_KEYS: Final[Sequence[str]] = (
    "gitignore_generated",
    "parallel",
    "visualizer",
)
KNOWN_ROOT_DIRECTORIES: Final[Sequence[str]] = (
    # cases are also generated in thi order
    "sample",
    "secret",
    "invalid_output",
    "invalid_answer",
    "invalid_input",
    "valid_output",
    # extension to the spec directories
    "testing_tool_test",
    "fuzz",
)
DEPRECATED_ROOT_DIRECTORIES: Final[Sequence[str]] = (
    "invalid_outputs",
    "invalid_answers",
    "invalid_inputs",
    "valid_outputs",
)


# Holds all inheritable configuration options. Currently:
# - config.solution
# - config.random_salt
# - config.retries
class Config:
    # Used at each directory or test case level.

    def __init__(
        self,
        problem: Problem,
        parser: Optional[YamlParser] = None,
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

        if parser is not None:
            if "solution" in parser.remaining:
                no_solution = parser.remaining["solution"] is None
                path = parser.extract_optional("solution", str)
                if path is not None:
                    self.needs_default_solution = False
                    self.solution = SolutionInvocation(problem, path)
                if no_solution:
                    self.needs_default_solution = False
                    self.solution = None
            self.random_salt = parser.extract("random_salt", self.random_salt)
            self.retries = parser.extract("retries", self.retries, ">= 0")


class Rule:
    # key: the dictionary key in the yaml file, i.e. `test_case`
    # name: the numbered test case name, i.e. `01-test_case`
    def __init__(
        self,
        problem: Problem,
        key: str,
        name: str,
        raw_yaml: YAML_TYPE,
        parser: YamlParser,
        parent: "AnyDirectoryRule",
    ) -> None:
        self.parent = parent

        # Yaml key of the current directory/test case.
        self.key = key
        # Filename of the current directory/test case.
        self.name: str = name
        # Path of the current directory/test case relative to data/.
        self.path: Path = parent.path / self.name
        # store Yaml
        self.yaml = raw_yaml

        self.config: Config = Config(problem, parser, parent_config=parent.config)


class TestcaseRule(Rule):
    def __init__(
        self,
        problem: Problem,
        generator_config: "GeneratorConfig",
        key: str,
        name: str,
        raw_yaml: YAML_TYPE,
        parser: YamlParser,
        parent: "AnyDirectoryRule",
        count_value: int,
    ) -> None:
        assert is_test_case(raw_yaml)

        # if False rule will be skipped during generation
        self.ok = True

        # root in /data
        self.root = (parent.path / name).parts[0]
        # Whether this test case is a sample.
        self.sample: bool = self.root == "sample"
        # each test case needs some kind of input
        self.required_in: list[list[str]] = [[".in"]]
        if self.sample:
            # for samples a statement in file is also sufficient
            self.required_in.append([".in.statement", ".in.download"])
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
        # 4. Linked files belonging to the same test case.
        self.linked = dict[str, str]()
        # map of ext to list of patterns used to check the generated test case.<ext>
        self.patterns = collections.defaultdict[str, list[re.Pattern[str]]](list)

        # Hash of test case for caching.
        self.hash: str

        # Yaml of rule
        self.rule = dict[str, str | int]()

        # Used by `fuzz`
        self.in_is_generated = False
        self.count_value = count_value

        # used to decide if this was supposed to be a duplicate or not
        self.intended_copy = has_count(parser.remaining)

        # used to handle duplicated test case rules
        self.copy_of = None

        # set during generate
        self.generate_success = False

        self.process = generator_config.process_test_case(parent.path / name)

        if name.endswith(".in"):
            name = name[:-3]
            parser.bar.error("Testcase names should not end with '.in'")

        try:
            super().__init__(problem, key, name, raw_yaml, parser, parent)

            # files to consider for hashing
            hashes = {}
            if not config.FILE_NAME_REGEX.fullmatch(name + ".in"):
                raise ParseException("Test case does not have a valid name.")

            if name == "test_group":
                raise ParseException(
                    "Test case must not be named 'test_group', this clashes with the group-level 'test_group.yaml'."
                )

            if raw_yaml is None:
                raise ParseException(
                    "Empty yaml entry (Testcases must be generated from entry not merely be mentioned)."
                )

            # checks
            satisfied = False
            msg = []
            for required in [[".generate"], [".copy"]] + self.required_in:
                satisfied = satisfied or all(x[1:] in parser.remaining for x in required)
                msg.append(" and ".join([x[1:] for x in required]))
            if not satisfied:
                raise ParseException(f"Testcase requires at least one of: {', '.join(msg)}.")
            if (
                not problem.interactive
                and not problem.multi_pass
                and "interaction" in parser.remaining
            ):
                raise ParseException(
                    "Testcase cannot have 'interaction' key for non-interactive/non-multi-pass problem."
                )
            if not self.sample:
                for ext in config.KNOWN_SAMPLE_TESTCASE_EXTENSIONS:
                    if ext[1:] in parser.remaining:
                        raise ParseException(f"Non sample test case cannot use '{ext[1:]}")
            if "submission" in parser.remaining and "ans" in parser.remaining:
                raise ParseException("Testcase cannot specify both 'submissions' and 'ans'.")

            # 1. generate
            command_string = parser.pop("generate")
            if command_string is not None:
                assert is_type(command_string, str, "generate")
                if len(command_string) == 0:
                    raise ParseException("'generate' must not be empty.")

                # first replace {{constants}}
                command_string = substitute(
                    command_string,
                    problem.settings.constants,
                    pattern=config.CONSTANT_SUBSTITUTE_REGEX,
                )

                # then replace {count}
                if "{count}" in command_string:
                    if has_count(parser.remaining):
                        command_string = command_string.replace("{count}", f"{self.count_value}")
                        self.intended_copy = False
                    else:
                        parser.bar.warn(
                            "Found {count} in generator command but no count in yaml. IGNORED."
                        )
                self.generator = GeneratorInvocation(problem, command_string)

                # IMPORTANT: The seed depends on white space, but
                # leading and trailing whitespace is stripped.
                seed_value = self.config.random_salt
                if self.count_value != 1:  # distinguish different count values
                    # IMPORTANT: We need to use `self.count_value - 1` for backwards compatibility.
                    seed_value += f":{self.count_value - 1}"
                seed_value += command_string.strip()
                self.seed = int(hash_string(seed_value), 16) % 2**31
                self.in_is_generated = True
                self.rule["gen"] = command_string
                if self.generator.uses_seed:
                    self.rule["seed"] = self.seed
                    self.intended_copy = False
                hashes[".in"] = self.generator.hash(self.seed)

            # 2. path
            copy_entry = parser.pop("copy")
            if copy_entry is not None:
                assert is_type(copy_entry, str, "copy")

                if Path(copy_entry).suffix in config.KNOWN_TEXT_DATA_EXTENSIONS:
                    parser.bar.warn(f"`copy: {copy_entry}` should not include the extension.")
                self.copy = resolve_path(copy_entry, allow_absolute=False, allow_relative=True)
                self.copy = problem.path / self.copy.parent / (self.copy.name + ".in")
                if self.copy.is_file():
                    self.in_is_generated = False
                self.rule["copy"] = str(self.copy)
                for ext in config.KNOWN_TESTCASE_EXTENSIONS:
                    if self.copy.with_suffix(ext).is_file():
                        hashes[ext] = hash_file_content(self.copy.with_suffix(ext))

            # 3./4. link to another file or hardcoded data
            for ext in config.KNOWN_TEXT_DATA_EXTENSIONS:
                key = ext[1:]
                value = parser.pop(key)
                if value is None:
                    continue

                # yaml can only be hardcoded (convert dict back to string)
                if key == "yaml":
                    if isinstance(value, dict):
                        value = write_yaml(value)
                        assert value is not None

                # 3. linked
                if (
                    isinstance(value, dict)
                    and len(value) == 1
                    and "link" in value
                    and isinstance(value["link"], str)
                    and key in ALLOWED_LINK_KEYS
                ):
                    link = value["link"]
                    if link not in ALLOWED_LINK_VALUES:
                        closest = difflib.get_close_matches(link, ALLOWED_LINK_VALUES, n=1)
                        hint = f" Did you mean: {closest[0]}?" if closest else ""
                        raise ParseException(f"Unknown link target `{link}`.{hint}")
                    key_type = key.split(".", 1)[0]
                    link_type = link.split(".", 1)[0]
                    if key_type != link_type:
                        raise ParseException(f"Crosslinking from {key} to {link} is not allowed.")
                    self.linked[ext] = f".{link}"
                elif isinstance(value, str):  # 4. hardcoded
                    if len(value) > 0 and value[-1] != "\n":
                        value += "\n"
                    self.hardcoded[ext] = value
                else:
                    raise ParseException(
                        f"{key} should either be a string or a map with only a link entry."
                    )

            for link, target in self.linked.items():
                # do not allow links to other links to avoid cycles
                if target in self.linked:
                    raise ParseException(
                        f"link from {link}->{target} is forbidden, {target} is also a link!"
                    )

            if ".in" in self.hardcoded:
                self.in_is_generated = False
                self.rule["in"] = self.hardcoded[".in"]
            for ext, value in self.hardcoded.items():
                hashes[ext] = hash_string(value)

            if "match" in parser.remaining:
                raw_match_entries = parser.remaining["match"]
                if isinstance(raw_match_entries, (str, list)):
                    parser.remaining["match"] = {"in": raw_match_entries}
            match_parser = parser.extract_parser("match")
            for ext in ["in", "ans"]:
                entries = match_parser.extract_optional_list(ext, object, allow_empty=True)
                for i, entry in enumerate(entries):
                    if not isinstance(entry, str):
                        generator_config.n_test_case_error += 1
                        match_parser.bar.error(f"match.{ext}[{i}] is not a string.")
                        continue
                    try:
                        self.patterns[ext].append(re.compile(entry, re.MULTILINE | re.DOTALL))
                    except re.error:
                        generator_config.n_test_case_error += 1
                        match_parser.bar.error(f"could not parse regex `{entry}`.")
            match_parser.check_unknown_keys()

            # Error for unknown keys.
            for any_key in UNIQUE_DIRECTORY_KEYS:
                parser.extract_reserved(any_key)

            # combine hashes
            self.hash = combine_hashes_dict(hashes)

            if self.hash in generator_config.rules_cache:
                self.copy_of = generator_config.rules_cache[self.hash]
                if id(self.copy_of.yaml) != id(self.yaml):
                    self.intended_copy = False
            else:
                generator_config.rules_cache[self.hash] = self

            known_ext = {*hashes.keys(), *self.linked.keys()}
            if not any(set(required) <= known_ext for required in self.required_in):
                generator_config.n_test_case_error += 1
                # An error is shown during generate.
        except ParseException as e:
            # For test cases we can handle the parse error locally since this does not influence much else
            parser.bar.error(e.message)
            self.ok = False
            generator_config.n_test_case_error += 1

    def _has_required_in(t, infile: Path) -> bool:
        for required in t.required_in:
            if all(infile.with_suffix(ext).is_file() for ext in required):
                return True
        return False

    class MetaYaml:
        def __init__(self, problem: Problem, test_case: "TestcaseRule") -> None:
            self._path = problem.tmpdir / "data" / test_case.hash / "meta_.yaml"
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
            self.rule = test_case.rule

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

        identical_exts = set()

        src_dir = problem.path / "data" / t.path.parent
        src = src_dir / (t.name + ".in")

        for ext in config.KNOWN_DATA_EXTENSIONS:
            source = src.with_suffix(ext)
            target = dst.with_suffix(ext)

            if source.is_file() and source in generator_config.known_files:
                generator_config.known_files.add(target)
                if target.exists() or target.is_symlink():
                    if target.is_symlink() and target.resolve() == source.resolve():
                        # identical -> skip
                        identical_exts.add(ext)
                    else:
                        # different -> overwrite
                        generator_config.remove(target)
                        ensure_symlink(target, source, relative=True)
                        bar.log(f"CHANGED: {target.name}")
                else:
                    # new file -> copy it
                    ensure_symlink(target, source, relative=True)
                    bar.log(f"NEW: {target.name}")
            elif target.exists() or target.is_symlink():
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

    def validate_in(
        t,
        problem: Problem,
        test_case: Testcase,
        meta_yaml: "TestcaseRule.MetaYaml",
        bar: ProgressBar,
    ) -> bool:
        assert t.process

        infile = problem.tmpdir / "data" / t.hash / "testcase.in"
        assert infile.is_file()

        if test_case.root == "testing_tool_test":
            return True

        input_validator_hashes = test_case.validator_hashes(validate.InputValidator, bar)
        if all(h in meta_yaml.input_validator_hashes for h in input_validator_hashes):
            return True

        if not test_case.validate_format(
            validate.Mode.INPUT,
            bar=bar,
            constraints=None,
            warn_instead_of_error=config.args.no_validators,
        ):
            if not config.args.no_validators:
                if t.generator:
                    command = t.generator.cache_command(t.seed if t.generator.uses_seed else None)
                    bar.warn(f"Failed generator command: {command}")
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
        test_case: Testcase,
        meta_yaml: "TestcaseRule.MetaYaml",
        bar: ProgressBar,
    ) -> bool:
        assert t.process

        infile = problem.tmpdir / "data" / t.hash / "testcase.in"
        assert infile.is_file()

        if test_case.root in ["invalid_input", "testing_tool_test"]:
            return True

        ansfile = infile.with_suffix(".ans")
        if not ansfile.is_file():
            bar.error("No .ans file was generated!")
            return False

        outfile = infile.with_suffix(".out")
        if not outfile.is_file() and test_case.root in [
            "invalid_output",
            "valid_output",
        ]:
            bar.error("No .out file was generated!")
            return False

        ans_out_validator_hashes = test_case.validator_hashes(validate.AnswerValidator, bar).copy()
        output_validator_hashes = test_case.validator_hashes(validate.OutputValidator, bar)

        mode = validate.Mode.ANSWER
        if test_case.root == "invalid_answer":
            mode = validate.Mode.INVALID
        elif test_case.root == "invalid_output":
            ans_out_validator_hashes.update(output_validator_hashes)
            mode = validate.Mode.INVALID
        elif test_case.root == "valid_output" or outfile.is_file():
            ans_out_validator_hashes.update(output_validator_hashes)
            mode = validate.Mode.VALID_OUTPUT

        if all(h in meta_yaml.ans_out_validator_hashes for h in ans_out_validator_hashes):
            return True

        if not test_case.validate_format(
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
                f'Found identical rule at {t.copy_of.path}. Use "count: <int>" if you want identical test cases (do not use {{seed}} or {{count}}).'
            )

        # Some early checks.
        if t.copy_of is not None and not t.copy_of.generate_success:
            bar.done(False, f"See {t.copy_of.path}. SKIPPED.")
            return
        if not t.ok:
            bar.done(False, "Rule contained errors. SKIPPED.")
            return
        if t.generator and t.generator.program is None:
            bar.done(False, "Generator didn't build. SKIPPED.")
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
            remove_path(tmp)

        def generate_linked(type: str) -> bool:
            # cache entries are already set in generate_from_rule
            for source_ext, target_ext in t.linked.items():
                source_type = source_ext.split(".", 2)[1]
                if source_type != type:
                    continue
                source = infile.with_suffix(source_ext)
                target = infile.with_suffix(target_ext)
                if not target.is_file():
                    bar.error(
                        f"link {source_ext[1:]}->{target_ext[1:]} is invalid since {target_ext[1:]} was not generated"
                    )
                ensure_symlink(source, target, relative=True)
            return True

        def generate_from_rule() -> bool:
            nonlocal meta_yaml

            # create expected cache entry for generate
            rule_hashes = dict[object, object]()
            if t.copy:
                rule_hashes["source_hash"] = t.hash
            for ext, string in t.hardcoded.items():
                rule_hashes["hardcoded_" + ext[1:]] = hash_string(string)
            for link, target in t.linked.items():
                rule_hashes["linked_" + link[1:]] = hash_string(target)
            if t.generator:
                rule_hashes["generator_hash"] = t.generator.hash(seed=t.seed)
                rule_hashes["generator"] = t.generator.cache_command(seed=t.seed)

            if not infile.is_file() or meta_yaml.rule_hashes != rule_hashes:
                # clear all generated files
                remove_path(cwd)
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
                    copied = False
                    for ext in config.KNOWN_DATA_EXTENSIONS:
                        ext_file = t.copy.with_suffix(ext)
                        file = infile.with_suffix(ext)
                        if is_local_symlink(ext_file):
                            dest_ext = "".join(ext_file.readlink().suffixes)
                            ensure_symlink(file, infile.with_suffix(dest_ext), relative=True)
                            copied = True
                        elif ext_file.is_file():
                            shutil.copy(ext_file, file, follow_symlinks=True)
                            copied = True
                    if not copied:
                        bar.warn(f"No files copied from {t.copy}.")

                # Step 3: Write hardcoded files.
                for ext, contents in t.hardcoded.items():
                    file = infile.with_suffix(ext)
                    if file.exists():
                        file.unlink()
                    # substitute in contents? -> No!
                    file.write_text(contents)

                # Step 4: Write linked files
                # Note: we cannot generate all links yet, since .ans files are not yet generated
                if not generate_linked("in"):
                    return False

                # Step 5: Error if infile was not generated.
                if not t._has_required_in(infile):
                    msg = ", ".join(" and ".join(required) for required in t.required_in)
                    bar.error(f"No {msg} file was generated!")
                    return False

                # Step 6: save which files where generated
                meta_yaml.generated_extensions = [
                    ext for ext in config.KNOWN_DATA_EXTENSIONS if infile.with_suffix(ext).is_file()
                ]

                # Step 7: update cache
                meta_yaml.rule_hashes = rule_hashes
                meta_yaml.write()

                # Step 8: check deterministic:
                check_deterministic(True)
            else:
                check_deterministic(False)

            assert t._has_required_in(infile), f"Failed to generate in file: {infile.name}"
            return True

        def check_match(test_case: Testcase, ext: str) -> bool:
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
                        file = test_case.in_path.with_suffix(f".{ext}")
                        if not file.is_file():
                            bar.error(f"Invalid match entry, {ext} was not generated")
                            return False
                        text = file.read_text()
                    match = pattern.search(text)
                    cache[name] = f"[{match.start()}, {match.end()})" if match else None
                    updated = True

                if cache[name]:
                    bar.debug(f"Found match for '{name}'': {cache[name]}")
                else:
                    bar.warn(f"Found no match for '{name}'")

            if updated:
                meta_yaml.write()
            return True

        def generate_from_solution(test_case: Testcase) -> bool:
            nonlocal meta_yaml

            if test_case.root in [
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
                    interactor_hash = test_case.validator_hashes(validate.OutputValidator, bar)
                    if (
                        t.config.solution
                        and (test_case.root == "sample" or config.args.interaction)
                        and needed(".interaction", interactor_hash)
                        and not any(
                            infile.with_suffix(ext).is_file() or ext in t.linked
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

        def generate_visualization(test_case: Testcase) -> bool:
            nonlocal meta_yaml

            if test_case.root in config.INVALID_CASE_DIRECTORIES:
                return True
            if test_case.root == "testing_tool_test":
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
            visualizer_args = test_case.get_test_case_yaml(bar).input_visualizer_args
            if output_visualizer is not None:
                if out_path.is_file() or problem.settings.ans_is_output:
                    if visualizer is None or out_path.is_file():
                        visualizer = output_visualizer
                        visualizer_args = test_case.get_test_case_yaml(bar).output_visualizer_args
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
                remove_path(feedbackcopy)

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
            assert infile.is_file()
            if not ansfile.is_file():
                ansfile.write_text("")
            return True

        def warn_override() -> None:
            def find_override(*exts: str) -> list[str]:
                found = [ext for ext in exts if infile.with_suffix(ext).is_file()]
                if len(found) > 1:
                    bar.warn(f"There should be at most one of {', '.join(found)}")
                return found

            statement_in = find_override(".in.statement", ".interaction")
            download_in = find_override(".in.download")
            if statement_in and not download_in:
                bar.warn(f"found {statement_in[0]} but no override for .in.download")
            if not statement_in and download_in:
                bar.warn(f"found {download_in[0]} but no override for .in.statement")

            statement_ans = find_override(".out", ".ans.statement", ".interaction")
            download_ans = find_override(".out", ".ans.download")
            if statement_ans and not download_ans:
                bar.warn(f"found {statement_ans[0]} but no override for .ans.download")
            if not statement_ans and download_ans:
                bar.warn(f"found {download_ans[0]} but no override for .ans.statement")

        def copy_generated() -> None:
            identical_exts = set()

            for ext in config.KNOWN_DATA_EXTENSIONS:
                source = infile.with_suffix(ext)
                target = target_infile.with_suffix(ext)

                if is_local_symlink(source):
                    generator_config.known_files.add(target)
                    dest_ext = "".join(source.readlink().suffixes)
                    dest = target_infile.with_suffix(dest_ext)
                    if not source.is_file():
                        bar.warn(
                            f"{target.name}->{dest.name} is broken since {dest.name} was not generated"
                        )
                    if target.exists() or target.is_symlink():
                        if target.is_symlink() and target.resolve() == dest.resolve():
                            # identical -> skip
                            identical_exts.add(ext)
                        else:
                            # different -> overwrite
                            ensure_symlink(target, dest, relative=True)
                            bar.log(f"CHANGED: {target.name}")
                    else:
                        # new link -> create it
                        ensure_symlink(target, dest, relative=True)
                        bar.log(f"NEW: {target.name}")
                elif source.is_file():
                    generator_config.known_files.add(target)
                    if target.exists() or target.is_symlink():
                        if not target.is_symlink() and source.read_bytes() == target.read_bytes():
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
                elif target.is_file() or target.is_symlink():
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

        def add_test_case_to_cache(test_case: Testcase) -> None:
            # Used to identify generated test cases
            generator_config.hashed_in.add(hash_file_content(infile))

            # check for duplicates
            test_hash = test_case.core_hash(bar)
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

        test_case: Optional[Testcase] = None
        if infile.is_file():
            # Step 3: check .in if needed
            test_case = Testcase(problem, infile, short_path=t.path / t.name)
            if not t.validate_in(problem, test_case, meta_yaml, bar):
                return

            # Step 3.1: check patterns
            if not check_match(test_case, "in"):
                return

            # Step 4: generate .ans and .interaction if needed
            if not generate_from_solution(test_case):
                return
            # Step 4.1: for interactive and/or multi-pass samples, generate empty .ans if it does not exist
            if not generate_empty_interactive_sample_ans():
                return
            # Step 4.2: link ans files
            if not generate_linked("ans"):
                return

            # Step 5: validate .ans (and .out if it exists)
            if not t.validate_ans_and_out(problem, test_case, meta_yaml, bar):
                return

            # Step 5.1: check patterns
            if not check_match(test_case, "ans"):
                return

            # Step 6: generate visualization if needed
            if not generate_visualization(test_case):
                return
        else:
            # Step 4.2: link ans files (This is independent of the infile)
            if not generate_linked("ans"):
                return

        # Step 7: warn if statement/download files are inconsistent
        warn_override()

        # Step 8: copy all generated files
        copy_generated()

        # Note that we set this to true even if not all files were overwritten -- a different log/warning message will be displayed for that.
        t.generate_success = True
        generator_config.failed -= 1
        generator_config.generated += 1
        if infile.is_file():
            assert test_case is not None
            add_test_case_to_cache(test_case)
        if config.args.action != "generate":
            bar.logged = True  # Disable redundant 'up to date' message in run mode.
        bar.done(message="SKIPPED: up to date")


# Helper that has the required keys needed from a parent directory.
class RootDirectoryRule:
    path = Path("")
    config = None
    numbered = False


class DirectoryRule(Rule):
    # Process yaml object for a directory.
    def __init__(
        self,
        problem: Problem,
        key: str,
        name: str,
        yaml: dict[object, object],
        parser: YamlParser,
        parent: "AnyDirectoryRule",
    ) -> None:
        assert is_directory(yaml)

        # The root DirectoryRule object has name ''.
        if not isinstance(parent, RootDirectoryRule):
            if not config.FILE_NAME_REGEX.fullmatch(name):
                raise ParseException("Directory does not have a valid name.", parent.path / name)

        super().__init__(problem, key, name, yaml, parser, parent)

        if isinstance(parent, RootDirectoryRule):
            for any_key in RESERVED_DIRECTORY_KEYS:
                parser.extract_reserved(any_key)
            for any_key in DEPRECATED_ROOT_KEYS:
                parser.extract_deprecated(any_key)
        else:
            for any_key in [*RESERVED_DIRECTORY_KEYS, *KNOWN_ROOT_KEYS]:
                parser.extract_reserved(any_key)

        self.test_group_yaml: object | Literal[False] = parser.remaining.pop(
            "test_group.yaml", False
        )
        self.numbered = isinstance(parser.remaining.get("data", None), list)

        # List of child TestcaseRule/DirectoryRule objects, filled by parse().
        self.data = list[TestcaseRule | DirectoryRule]()
        # Map of short_name => TestcaseRule, filled by parse().
        self.includes = dict[str, TestcaseRule]()

    # The @overload definitions are purely here for static typing reasons.
    # This overload takes a single function as argument, which is used for both files and directories.
    @overload
    def walk(
        self,
        test_case_f: Optional[Callable[["TestcaseRule | DirectoryRule"], object]],
        *,
        skip_restricted: bool = True,
    ) -> None: ...

    # This overload takes one function for test cases and a separate function for directories.
    @overload
    def walk(
        self,
        test_case_f: Optional[Callable[[TestcaseRule], object]],
        dir_f: Optional[Callable[["DirectoryRule"], object]],
        *,
        skip_restricted: bool = True,
    ) -> None: ...

    # Map a function over all test cases directory tree.
    # dir_f by default reuses test_case_f
    def walk(
        self,
        test_case_f: Optional[
            Callable[["TestcaseRule | DirectoryRule"], object] | Callable[[TestcaseRule], object]
        ] = None,
        dir_f: (
            Literal[True]
            | Optional[
                Callable[["TestcaseRule | DirectoryRule"], object]
                | Callable[["DirectoryRule"], object]
            ]
        ) = True,
        *,
        skip_restricted: bool = True,
    ) -> None:
        if dir_f is True:
            dir_f = cast(Optional[Callable[["TestcaseRule | DirectoryRule"], object]], test_case_f)
        if dir_f:
            dir_f(self)

        for d in self.data:
            if isinstance(d, DirectoryRule):
                d.walk(test_case_f, dir_f)
            elif isinstance(d, TestcaseRule):
                if not d.process and skip_restricted:
                    continue
                if test_case_f:
                    test_case_f(d)
            else:
                assert False

    def generate(
        d, problem: Problem, generator_config: "GeneratorConfig", bar: ProgressBar
    ) -> None:
        # Generate the current directory:
        # - Create the directory.
        # - Write test_group.yaml.
        # - Link included test cases.
        #   - Input of included test cases are re-validated with the
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

            if not generator_config.process_test_case(new_case):
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

            # Check if the test case was already validated.
            meta_yaml = TestcaseRule.MetaYaml(problem, t)
            test_case = Testcase(problem, infile, short_path=new_case)

            # Step 1: validate .in
            if not t.validate_in(problem, test_case, meta_yaml, bar):
                continue

            # Step 2: validate .ans (and .out if it exists)
            if not t.validate_ans_and_out(problem, test_case, meta_yaml, bar):
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


AnyDirectoryRule = RootDirectoryRule | DirectoryRule


class GeneratorConfig:
    # Parse generators.yaml.
    def __init__(self, problem: Problem, restriction: Optional[Sequence[Path]] = None) -> None:
        self.problem = problem
        yaml_path = self.problem.path / "generators" / "generators.yaml"
        # we differentiate between two types or errors:
        # 1. n_test_case_error: parse errors that only influence one test case
        # 2. n_parse_error all: other parse errors
        # only type 2 is considered critical
        self.n_test_case_error = 0
        self.n_parse_error = 0

        # A map of paths `secret/test_group/test_case` to their canonical TestcaseRule.
        # For generated cases this is the rule itself.
        # For included cases, this is the 'resolved' location of the test case that is included.
        self.known_cases = dict[Path, TestcaseRule]()
        # A map of paths `secret/test_group` to DirectoryRule.
        self.known_directories = dict[Path, DirectoryRule]()
        # Used for cleanup
        self.known_files = set[Path]()
        # A map from key to (is_included, list of test cases and directories),
        # used for `include` statements.
        self.known_keys = collections.defaultdict[
            str, tuple[bool, list[TestcaseRule | DirectoryRule]]
        ](lambda: (False, []))
        # A set of test case rules, including seeds.
        self.rules_cache = dict[str, TestcaseRule]()
        # The set of generated test cases keyed by hash(test_case).
        self.generated_test_cases = dict[str, TestcaseRule]()
        # Path to the trash directory for this run
        self.trash_dir: Optional[Path] = None
        # Set of hash(.in) for all generated test cases
        self.hashed_in = set[str]()
        # Files that should be processed
        self.restriction = restriction
        # replaced during _parse_yaml
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

        bar = PrintBar("generators.yaml")
        try:
            self.root_dir = self._parse_root(self.yaml, bar)
        except ParseException as e:
            self.n_parse_error += 1
            bar.start(e.path).error(e.message)

        if self.n_parse_error:
            bar.error("could not be parsed")
        elif self.n_test_case_error:
            bar.warn("contains errors")
        bar.finalize(print_done=False)

    def _parse_root(self, raw_yaml: object, bar: BAR_TYPE) -> DirectoryRule:
        if raw_yaml is None:
            raw_yaml = dict()

        if not isinstance(raw_yaml, dict):
            raise ParseException("could not parse generators.yaml, must be a dict.")
        if not is_directory(raw_yaml):
            raise ParseException(
                "could not parse generators.yaml, root must represent a directory."
            )

        parser = YamlParser("generators.yaml", raw_yaml, bar=bar)

        # we don't really care about the version
        parser.pop("version")

        # generators can only be at the root
        def parse_generators(parser: YamlParser) -> dict[Path, list[Path]]:
            generators = {}
            for gen in list(parser.remaining):
                if not isinstance(gen, str):
                    continue

                if (
                    gen.startswith("/")
                    or Path(gen).is_absolute()
                    or not config.FILE_NAME_REGEX.fullmatch(gen)
                ):
                    parser.bar.warn(f"key `{gen}` is invalid. SKIPPED.")
                    continue

                path = Path("generators") / gen
                deps = parser.extract_optional_list(gen, str, allow_value=False, allow_empty=True)
                if not deps:
                    parser.bar.warn(f"Generator `{gen}` is missing dependencies. SKIPPED")
                    continue

                generators[path] = [Path("generators") / d for d in deps]

            parser.check_unknown_keys()
            return generators

        self.generators = parse_generators(parser.extract_parser("generators"))

        # pre determine the number of test cases for auto numbering
        # This parser is quite forgiving
        def count(yaml: dict[object, object]) -> int:
            ds = yaml.get("data")
            if isinstance(ds, dict):
                ds = [ds]
                numbered = False
            else:
                numbered = True
            if not isinstance(ds, list):
                return 0
            total = 0
            for elem in ds:
                if not isinstance(elem, dict):
                    continue
                for key, entry in elem.items():
                    if is_test_case(entry) and numbered:
                        total += len(parse_count(entry))
                    elif is_directory(entry):
                        total += count(entry)
            return total

        num_numbered_test_cases = count(parser.remaining)
        next_test_case_id = itertools.count(1)

        # add an explicit rule (directory or test case). Not includes!
        def add_known(parser: YamlParser, rule: TestcaseRule | DirectoryRule) -> None:
            path = rule.path
            name = path.name
            if isinstance(rule, TestcaseRule):
                self.known_cases[path] = rule
            elif isinstance(rule, DirectoryRule):
                self.known_directories[path] = rule

            is_included, cases_list = self.known_keys[rule.key]
            cases_list.append(rule)
            if is_included and len(cases_list) == 2:
                parser.bar.warn(f"Already included key {name} is reused: {rule.path}.")

        # might return multiple rules because of count
        def parse_test_case(
            key: str,
            name_gen: Iterator[str],
            raw_yaml: object,
            bar: BAR_TYPE,
            parent: DirectoryRule,
        ) -> list[TestcaseRule]:
            assert is_test_case(raw_yaml)

            if isinstance(raw_yaml, dict):
                parser_yaml = raw_yaml
            elif isinstance(raw_yaml, str):
                if raw_yaml.endswith(".in"):
                    bar.warn(f"Use the new `copy: path/to/case` key instead of {raw_yaml}.")
                    parser_yaml = {"copy": raw_yaml[:-3]}
                else:
                    parser_yaml = {"generate": raw_yaml}
            else:
                parser_yaml = {}

            count_list = parse_count(raw_yaml)
            # pad numbers with leading zeros if counts are consecutive
            is_consecutive = max(count_list) - min(count_list) == len(count_list) - 1
            padding = max(len(str(v)) for v in count_list) if is_consecutive else 0

            ts: list[TestcaseRule] = []
            for i, count_value in enumerate(count_list):
                parser = YamlParser("generators.yaml", parser_yaml, bar=bar)
                name = next(name_gen)
                if has_count(parser.remaining):
                    name += f"-{count_value:0{padding}}"

                t = TestcaseRule(
                    self.problem, self, key, name, raw_yaml, parser, parent, count_value
                )
                if t.ok:
                    parser.pop("count")
                    parser.check_unknown_keys()

                if t.path in self.known_cases:
                    # TODO: how can this happen?
                    bar.error("was already parsed. SKIPPED.")
                else:
                    add_known(parser, t)
                    ts.append(t)
            return ts

        # recursively parses children as well
        def parse_directory(
            key: str,
            name_gen: Iterator[str],
            raw_yaml: object,
            parser: YamlParser,
            parent: AnyDirectoryRule,
        ) -> DirectoryRule:
            assert is_directory(raw_yaml)

            d = DirectoryRule(self.problem, key, next(name_gen), raw_yaml, parser, parent)
            add_known(parser, d)
            if isinstance(parent, RootDirectoryRule) and d.numbered:
                raise ParseException("root directory must not be numbered.")

            # 1. gather all includes
            # => prohibits including our own children
            included_test_cases = []

            def add_included_case(t: TestcaseRule) -> None:
                included_test_cases.append(t)

            def add_included_dir(d: DirectoryRule) -> None:
                included_test_cases.extend(d.includes.values())

            includes = parser.extract_optional_list("include", object, allow_empty=True)
            for i, include in enumerate(includes):
                if not isinstance(include, str):
                    self.n_parse_error += 1
                    parser.bar.error(f"Include {i} should be a test case/group key. SKIPPED.")
                    continue

                if "/" in include:
                    self.n_parse_error += 1
                    parser.bar.error(
                        f"Include {i}:{include} should be a test case/group key, not a path. SKIPPED."
                    )
                    continue

                if include not in self.known_keys:
                    self.n_parse_error += 1
                    parser.bar.error(
                        f"Unknown include key {i}:{include} does not refer to a previous test case. SKIPPED."
                    )
                    continue

                is_included, cases_list = self.known_keys[include]
                if len(cases_list) != 1:
                    self.n_parse_error += 1
                    parser.bar.error(f"Included key {i}:{include} is ambiguous. SKIPPED.")
                    continue

                self.known_keys[include] = (True, cases_list)
                rule = cases_list[0]
                if isinstance(rule, TestcaseRule):
                    add_included_case(rule)
                else:
                    rule.walk(add_included_case, add_included_dir, skip_restricted=False)

            data = parser.extract_optional_list("data", object, allow_empty=True)
            assert is_list_type(data, dict, "data")

            # 2. pre determine the number of test child test groups
            # (only used if d.numbered is True)
            # This parser is quite forgiving
            num_test_groups = 0
            for entry in data:
                num_test_groups += sum(1 for yaml in entry.values() if is_directory(yaml))
            next_test_group_id = itertools.count(1)

            # 3. parse recursive
            for i, entry in enumerate(data):
                if d.numbered and len(entry) != 1:
                    found_keys = [k for k in UNIQUE_TESTCASE_KEYS if k in entry]
                    if found_keys:
                        parser.bar.error(
                            f"Numbered test case {d.path}[{i}] must have exactly one entry. SKIPPED.\nTo specify {'/'.join(found_keys)}, indent one more level."
                        )
                    else:
                        parser.bar.error(
                            f"Numbered test case/group {d.path}[{i}] must have exactly one entry. SKIPPED."
                        )
                    self.n_parse_error += 1
                    continue

                sub_parser = YamlParser(parser.source, entry, bar=parser.bar)

                # Process named children alphabetically, but not in the root directory.
                # There, process in the 'natural order'.
                if isinstance(parent, RootDirectoryRule):
                    valid_keys: Sequence[str | None] = KNOWN_ROOT_DIRECTORIES
                    for deprecated_key in DEPRECATED_ROOT_DIRECTORIES:
                        sub_parser.extract_deprecated(deprecated_key, deprecated_key[:-1])
                else:
                    valid_keys = [
                        k for k in sub_parser.remaining.keys() if isinstance(k, (type(None), str))
                    ]
                    valid_keys.sort(key=lambda k: k or "")

                for valid_key in valid_keys:
                    if valid_key not in sub_parser.remaining:
                        continue
                    child_yaml = sub_parser.remaining.pop(valid_key)
                    child_key = valid_key or ""

                    if d.numbered:
                        if is_directory(child_yaml):
                            child_name = next_numbered_name(
                                child_key, next_test_group_id, num_test_groups
                            )
                        elif is_test_case(child_yaml):
                            child_name = next_numbered_name(
                                child_key, next_test_case_id, num_numbered_test_cases
                            )
                        else:
                            child_name = itertools.repeat(child_key)
                    else:
                        if not child_key:
                            self.n_parse_error += 1
                            sub_parser.bar.error(
                                "Unnumbered test case/group must not have an empty key. SKIPPING."
                            )
                            continue
                        child_name = itertools.repeat(child_key)

                    child_path = ".".join(d.path.parts + (child_key or '""',))
                    child_bar = sub_parser.bar.start(child_path)
                    if is_directory(child_yaml):
                        child_parser = YamlParser(sub_parser.source, child_yaml, bar=child_bar)
                        cd = parse_directory(child_key, child_name, child_yaml, child_parser, d)
                        d.data.append(cd)
                        child_parser.check_unknown_keys()
                    elif is_test_case(child_yaml):
                        ts = parse_test_case(child_key, child_name, child_yaml, child_bar, d)
                        d.data.extend(ts)
                    else:
                        self.n_parse_error += 1
                        sub_parser.bar.error(
                            f"{valid_key} is neither a test case nor a directory. SKIPPING."
                        )
                        continue

                sub_parser.check_unknown_keys()

            # 4. handle includes (check collistions with recursively parsed stuff)
            for t in included_test_cases:
                target = t.path
                name = target.name
                p = d.path / name
                if p in self.known_cases:
                    if target != self.known_cases[p].path:
                        if self.known_cases[p].path == p:
                            parser.bar.error(f"conflict with included case {target}.")
                        else:
                            parser.bar.error(
                                f"included with multiple targets {target} and {self.known_cases[p].path}."
                            )
                        self.n_parse_error += 1
                else:
                    self.known_cases[p] = t
                    d.includes[name] = t
            return d

        root = parse_directory("", itertools.repeat(""), raw_yaml, parser, RootDirectoryRule())
        if config.args.action in [
            "generate",
            "all",
            "constraints",
            "run",
            "time_limit",
            "check_testing_tool",
        ]:
            parser.check_unknown_keys(warn=False)
        return root

    # test_case_short_path: secret/1.in
    def process_test_case(self, relative_test_case_path: Path) -> bool:
        if not self.restriction:
            return True
        absolute_test_case_path = (
            self.problem.path / "data" / relative_test_case_path.with_suffix("")
        )
        for p in self.restriction:
            for basedir in get_basedirs(self.problem, "data"):
                if absolute_test_case_path.is_relative_to(basedir / p):
                    return True
        return False

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

        def count_dir(d: DirectoryRule) -> None:
            for name in d.includes:
                item_names.append(d.path / name)

        self.root_dir.walk(None, count_dir)
        bar = ProgressBar("Generate", items=item_names)

        # Testcases are generated in two steps:
        # 1. Generate directories and unique test cases listed in generators.yaml.
        # 2. Generate duplicates of known test cases. All directories should already exists
        #    Each directory is only started after previous directories have
        #    finished and handled by the main thread, to avoid problems with
        #    included test cases.

        # 1
        def runner(t: TestcaseRule) -> None:
            if t.copy_of is None:
                t.generate(self.problem, self, bar)

        p = parallel.new_queue(runner)

        def generate_dir(d: DirectoryRule) -> None:
            p.join()
            d.generate(self.problem, self, bar)

        self.root_dir.walk(p.put, generate_dir)
        p.done()

        # 2
        def runner_copies(t: TestcaseRule) -> None:
            if t.copy_of is not None:
                t.generate(self.problem, self, bar)

        p = parallel.new_queue(runner_copies)

        def generate_includes(d: DirectoryRule) -> None:
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

    # move a file or directory into the trash directory
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
                not path.is_dir() and not self.process_test_case(local),
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

    # add all test cases specified as copy keys in the generators.yaml
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

        data = self.yaml if self.has_yaml else CommentedMap()
        assert isinstance(data, CommentedMap)

        parent = ryaml_get_or_add(data, "data")
        parent = ryaml_get_or_add(parent, "secret")
        entry = ryaml_get_or_add(parent, "data", CommentedSeq)

        bar = ProgressBar("Adding", items=in_files)
        for in_file in sorted(in_files, key=lambda x: x.name):
            bar.start(str(in_file))
            if not (self.problem.path / in_file).exists():
                bar.warn("file not found. SKIPPED.")
            elif in_file in known:
                bar.log("already found in generators.yaml. SKIPPED.")
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

        yaml_path = self.problem.path / "generators" / "generators.yaml"
        write_yaml(data, yaml_path)
        bar.finalize()
        return True

    # reorder all test cases in the given directories
    def reorder(self) -> bool:
        if self.n_parse_error + self.n_test_case_error > 0:
            return False

        directory_rules = set()
        assert config.args.testcases is not None  # set in cli.py
        for t in config.args.testcases:
            path = t.relative_to("data")
            parts = path.parts
            if not parts:
                warn("Cannot reorder Root directory. SKIPPED.")
            elif parts[0] in config.INVALID_CASE_DIRECTORIES:
                warn(f"{t} is used for invalid test data. SKIPPED.")
            elif parts[0] == "valid_output":
                warn(f"{t} is used for valid test data. SKIPPED.")
            elif parts[0] == "testing_tool_test":
                warn(f"{t} is used to test the testing tool. SKIPPED.")
            elif path not in self.known_directories:
                warn(f"{t} is not a generated directory. SKIPPED.")
            elif not self.known_directories[path].numbered:
                warn(f"{t} is not numbered. SKIPPED.")
            elif not self.known_directories[path].data:
                warn(f"{t} is empty. SKIPPED.")
            else:
                directory_rules.add(self.known_directories[path])

        data = self.problem.path / "data"

        test_case_filter = set()
        for d in directory_rules:
            for c in d.data:
                if isinstance(c, TestcaseRule):
                    test_case_filter.add(data / c.path.parent / (c.name + ".in"))

        ts_pair = self.problem.prepare_run()
        if not ts_pair:
            return False

        test_cases = [t for t in ts_pair[0] if t.in_path in test_case_filter]

        def not_accepted(s: run.Submission) -> bool:
            # If a submission is permitted to get a non AC verdict on any test case
            # it is not an accepted submission
            return any({Verdict.ACCEPTED} != s.expectations.all_permitted(t) for t in test_cases)

        submissions = [s for s in ts_pair[1] if not_accepted(s)]

        if not test_cases:
            error("No test cases found.")
            return False
        if not submissions:
            error("No rejected submissions found.")
            return False

        ok, verdict_table = Problem.run_some(test_cases, submissions)
        # ok == False only indicates that some submission did not Fail

        test_case_paths = {t.in_path.relative_to(data).with_suffix("") for t in test_cases}
        max_test_case_len = max([len(str(t)) for t in test_case_paths])
        for d in directory_rules:
            eprint()
            eprint(f"{Fore.CYAN}Reorder{Style.RESET_ALL}: {d.path}")

            # directory must be numbered
            assert isinstance(d.yaml, dict)
            assert "data" in d.yaml
            assert isinstance(d.yaml["data"], list)
            assert all(isinstance(e, dict) and len(e) == 1 for e in d.yaml["data"])

            # don't move unknown test cases/groups
            test_nodes = {
                id(c.yaml): c.path.as_posix() for c in d.data if c.path in test_case_paths
            }
            others = [e for e in d.yaml["data"] if id(next(iter(e.values()))) not in test_nodes]

            class TestcaseResult:
                def __init__(self, yaml: dict[object, object]) -> None:
                    self.yaml = yaml
                    test_case_yaml = next(iter(yaml.values()))
                    assert isinstance(test_case_yaml, (str, dict, type(None)))
                    self.name = test_nodes[id(test_case_yaml)]
                    self.count = len(parse_count(test_case_yaml))
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
                    return f"{Fore.CYAN}Reorder{Style.RESET_ALL}: {self.name:<{max_test_case_len}} {''.join(self.result)}"

                def score(self, weights: list[int]) -> float:
                    return sum(weights[i] * x for i, x in self.scores) / self.count

                def update(self, weights: list[int]) -> list[int]:
                    # the weights for each submission that did not fail on this test case get doubled
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

            # Each submission is initially assigned a weight of one. The weight contributes to the score of a test case if
            # the submission fails on this test case. If a test case is selected the weights for each submission that it fails
            # get halved (or all other get doubled) to encourage making the remaining submissions fail. We greedily pick the
            # test case that has the heighest score. Note that we additionally consider the type of failing (WA/TLE/RTE)
            # see class TestcaseResult.
            # Worstcase runtime test cases^2 * submissions
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
                if result.yaml in done:
                    # skip if another rule for the same count was already added
                    continue
                done.append(result.yaml)
                weights = result.update(weights)
                localbar.log("moved to front")
                localbar.done()

            for _ in todo:
                bar.skip()
            bar.finalize()

            # move all unknown subgroups/test cases to the end (keeping their relative order)
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
        return self.n_parse_error + self.n_test_case_error == 0


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
                remove_path(d)


# Clean data/ and tmpdir/data/
def clean_data(problem: Problem, data: bool = True, cache: bool = True) -> None:
    dirs = [
        problem.path / "data" if data else None,
        problem.tmpdir / "data" if cache else None,
    ]
    for d in dirs:
        if d is not None:
            remove_path(d)


def generate(problem: Problem) -> bool:
    clean_trash(problem)

    if config.args.clean:
        clean_data(problem, True, True)
        return True

    gen_config = GeneratorConfig(problem, config.args.testcases)
    if gen_config.n_parse_error > 0:
        return False

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
