import datetime
import difflib
import itertools
import math
import re
import shutil
import threading
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Optional, overload, TYPE_CHECKING

from colorama import Fore, Style
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scanner import ScannerError

from bapctools import (
    check_testing_tool,
    config,
    interactive,
    latex,
    parallel,
    validate,
    validator_tests,
    verdicts,
)
from bapctools.expectations import Expectations, Person
from bapctools.run import Submission
from bapctools.test_case import TestCase, TestCaseOverrides, TestGroup
from bapctools.util import (
    BAR_TYPE,
    drop_suffix,
    eprint,
    error,
    ExecStatus,
    fatal,
    generate_problem_uuid,
    glob,
    is_uuid,
    log,
    math_eval,
    once,
    once_per_instance,
    PrintBar,
    ProgressBar,
    read_yaml,
    remove_path,
    resolve_path_argument,
    ryaml_get_or_add,
    shorten_path,
    verbose,
    warn,
    write_yaml,
    YamlParser,
)
from bapctools.validate import (
    AnswerValidator,
    AnyValidator,
    ConstraintsDict,
    InputValidator,
    OutputValidator,
)
from bapctools.visualize import AnyVisualizer, InputVisualizer, OutputVisualizer

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools.program import Program


class Keywords:
    def __init__(self, parser: YamlParser):
        self.synonyms = dict[str, str]()
        self.keywords = set[str]()

        synonyms_parser = parser.extract_parser("synonyms")
        for key, value in synonyms_parser.remaining.items():
            if not isinstance(key, str):
                warn(f"invalid entry `{key}` in keywords.yaml. SKIPPED.")
                continue
            self.keywords.add(key)
            if not isinstance(value, str):
                warn(f"invalid entry `{value}` in keywords.yaml. SKIPPED.")
                continue
            self.keywords.add(value)
            self.synonyms[key] = value

        def parse(yaml: object, parent: Optional[str] = None) -> None:
            if yaml is None:
                pass  # ignore empty leaves
            elif isinstance(yaml, dict):
                for key, value in yaml.items():
                    if not isinstance(key, str):
                        warn(f"invalid entry `{key}` in keywords.yaml. SKIPPED.")
                    else:
                        parse(key, parent)
                        parse(value, key)
            elif isinstance(yaml, list):
                for entry in yaml:
                    parse(entry, parent)
            elif isinstance(yaml, str):
                if parent is not None:
                    self.keywords.add(yaml)
            else:
                warn(f"invalid entry `{yaml}` in keywords.yaml. SKIPPED.")

        parse(parser.remaining)

    def find(self, key: str) -> Optional[str]:
        matches = difflib.get_close_matches(key, self.keywords, n=1, cutoff=0.8)
        closest = matches[0] if matches else None
        seen = set[str]()
        while closest in self.synonyms:
            if closest in seen:
                error(f"could not resolve {closest}. keywords.yaml contains cycle.")
            seen.add(closest)
            closest = self.synonyms[closest]
        if closest is not None:
            for found in seen:
                self.synonyms[found] = closest
        return closest


@once
def keywords() -> Keywords:
    raw_keywords = read_yaml(config.RESOURCES_ROOT / "config" / "keywords.yaml")
    if not isinstance(raw_keywords, dict):
        fatal("could not parse keywords.yaml.")
    return Keywords(YamlParser("keywords.yaml", raw_keywords))


class ProblemCredits:
    def __init__(self, parser: YamlParser):
        self.authors: list[Person] = []
        self.contributors: list[Person] = []
        self.testers: list[Person] = []
        self.translators: dict[str, list[Person]] = {}
        self.packagers: list[Person] = []
        self.acknowledgements: list[Person] = []

        parser.extract_deprecated("author", "credits.authors")
        if "credits" not in parser.remaining:
            return
        if isinstance(parser.remaining["credits"], str):
            self.authors = [
                Person("problem.yaml", parser.extract("credits", ""), "credits", parser.bar)
            ]
            return

        credits = parser.extract_parser("credits")

        self.authors = Person.extract_optional_persons(credits, "authors")
        self.contributors = Person.extract_optional_persons(credits, "contributors")

        translators = credits.extract_parser("translators")
        self.translators = {}
        for lang in list(translators.remaining.keys()):
            if not isinstance(lang, str):
                parser.bar.warn(
                    f"invalid language `{lang}` for {translators.parent_str} in problem.yaml. SKIPPED."
                )
            else:
                self.translators[lang] = Person.extract_optional_persons(translators, lang)

        self.testers = Person.extract_optional_persons(credits, "testers")
        self.packagers = Person.extract_optional_persons(credits, "packagers")
        self.acknowledgements = Person.extract_optional_persons(credits, "acknowledgements")

        credits.check_unknown_keys()


@dataclass(frozen=True)
class ProblemSource:
    name: str
    url: Optional[str] = None

    def __repr__(self) -> str:
        return self.name + (f" ({self.url})" if self.url else "")


class ProblemSources(list[ProblemSource]):
    def __init__(self, parser: YamlParser):
        def parse_source(source: YamlParser) -> ProblemSource:
            name = source.extract_optional("name", str)
            url = source.extract_optional("url", str)
            if name is None:
                parser.bar.warn(f"problem.yaml: `name` is required in {source.parent_str}")
                name = ""
            source.check_unknown_keys()
            return ProblemSource(name, url)

        parser.extract_deprecated("source_url", "source.url")
        if "source" not in parser.remaining:
            return
        if isinstance(parser.remaining["source"], str):
            self.append(ProblemSource(parser.extract("source", "")))
            return
        if isinstance(parser.remaining["source"], dict):
            self.append(parse_source(parser.extract_parser("source")))
            return
        if isinstance(parser.remaining["source"], list):
            sources = parser.extract("source", list[object]())
            for i, source in enumerate(sources):
                if isinstance(source, str):
                    self.append(ProblemSource(source))
                elif isinstance(source, dict):
                    self.append(parse_source(YamlParser("problem.yaml", source, f"source[{i}]")))
                else:
                    parser.bar.warn(
                        f"problem.yaml key `source[{i}]` does not have the correct type. SKIPPED."
                    )
            return
        parser.bar.warn("problem.yaml key `source` does not have the correct type")


class ProblemLimits:
    def __init__(
        self,
        parser: YamlParser,
        problem: "Problem",
        problem_settings: "ProblemSettings",
    ):
        # Known keys:
        # (defaults from https://icpc.io/problem-package-format/spec/2025-09.html#limits)
        time_multipliers = parser.extract_parser("time_multipliers")
        parser.extract_deprecated("time_multiplier", "ac_to_time_limit")
        self.ac_to_time_limit = time_multipliers.extract("ac_to_time_limit", 2.0, ">= 1")
        parser.extract_deprecated("time_safety_margin", "time_limit_to_tle")
        self.time_limit_to_tle = time_multipliers.extract("time_limit_to_tle", 1.5, ">= 1")
        time_multipliers.check_unknown_keys()

        self.time_limit_is_default: bool = "time_limit" not in parser.remaining
        self.time_resolution: float = parser.extract("time_resolution", 1.0, "> 0")  # in seconds
        self.raw_time_limit: float = parser.extract("time_limit", self.time_resolution, "> 0")
        time_steps = self.raw_time_limit / self.time_resolution
        if abs(time_steps - round(time_steps)) >= 0.0001:
            parser.bar.error(
                f"problem.yaml time_limit ({self.raw_time_limit}) is not an integer multiple of time_resolution ({self.time_resolution})"
            )

        self.memory: int = parser.extract("memory", config.DEFAULT_MEMORY, "> 0")  # in MiB
        self.output: int = parser.extract("output", config.DEFAULT_OUTPUT, "> 0")  # in MiB
        self.code: int = parser.extract("code", config.DEFAULT_CODE, "> 0")  # in KiB
        self.compilation_time: int = parser.extract(
            "compilation_time", config.DEFAULT_COMPILATION_TIME, "> 0"
        )  # in seconds
        self.compilation_memory: int = parser.extract(
            "compilation_memory", config.DEFAULT_COMPILATION_MEMORY, "> 0"
        )  # in MiB
        self.validation_time: int = parser.extract(
            "validation_time", config.DEFAULT_VALIDATION_TIME, "> 0"
        )  # in seconds
        self.validation_memory: int = parser.extract(
            "validation_memory", config.DEFAULT_VALIDATION_MEMORY, "> 0"
        )  # in MiB
        self.validation_output: int = parser.extract(
            "validation_output", config.DEFAULT_VALIDATION_OUTPUT, "> 0"
        )  # in MiB
        if problem_settings.multi_pass:
            self.validation_passes: Optional[int] = parser.extract("validation_passes", 2, ">= 2")
        elif "validation_passes" in parser.remaining:
            parser.pop("validation_passes")
            parser.bar.warn(
                "limit: validation_passes is only used for multi-pass problems. SKIPPED."
            )
            self.validation_passes = None

        # BAPCtools extensions:
        self.generator_time: int = parser.extract("generator_time", 60, "> 0")  # in seconds
        self.visualizer_time: int = parser.extract("visualizer_time", 60, "> 0")  # in seconds

        # warn for deprecated timelimit files
        if (problem.path / ".timelimit").is_file():
            parser.bar.warn("A .timelimit file is DEPRECATED. Use limits.time_limit instead.")
        if (problem.path / "domjudge-problem.ini").is_file():
            parser.bar.warn(
                "domjudge-problem.ini is DEPRECATED. Use limits.time_limit if you want to set a timelimit."
            )

        parser.check_unknown_keys()

        # adjust actual time_limit based on local_time_multiplier
        self.time_limit: float = self.raw_time_limit
        if config.args.local_time_multiplier is not None:
            self.time_limit *= config.args.local_time_multiplier

        # Override limmits by command line arguments.
        if config.args.time_limit:
            self.time_limit = config.args.time_limit
            self.raw_time_limit = config.args.time_limit
        self.timeout: int = int(config.args.timeout or self.time_limit_to_tle * self.time_limit + 1)
        if config.args.timeout:
            self.validation_time = self.generator_time = self.visualizer_time = config.args.timeout
        if config.args.memory:
            self.memory = self.compilation_memory = self.validation_memory = config.args.memory


class ProblemSettings:
    def __init__(
        self,
        parser: YamlParser,
        problem: "Problem",
    ):
        if isinstance(parser.remaining.get("name", None), str):
            parser.remaining["name"] = {"en": parser.remaining["name"]}

        # Known keys:
        # (defaults from https://icpc.io/problem-package-format/spec/2025-09.html#problem-metadata)
        self.problem_format_version: str = parser.extract("problem_format_version", "legacy-icpc")

        if self.problem_format_version.startswith("legacy"):
            parser.bar.fatal("legacy is no longer supported, try running 'bt upgrade'")
        elif self.problem_format_version != config.SPEC_VERSION:
            parser.bar.fatal(f"unrecognized problem_format_version: {self.problem_format_version}")

        parser.extract_deprecated("validation", "type")
        if "type" not in parser.remaining:
            mode = {"pass-fail"}
        elif isinstance(parser.remaining["type"], str):
            mode = set(parser.extract("type", "pass-fail").split())
        elif isinstance(parser.remaining["type"], list):
            mode = set(parser.extract_optional_list("type", str))
            if not mode:
                mode = {"pass-fail"}
        else:
            parser.bar.fatal("problem.yaml: `type` must be a string or a sequence")
        unrecognized_type = mode - {"pass-fail", "interactive", "multi-pass"}
        if unrecognized_type:
            parser.bar.fatal(
                f"""problem.yaml: unrecognized value{
                    "" if len(unrecognized_type) == 1 else "s"
                } for `type`: {" ".join(sorted(unrecognized_type))}"""
            )
        self.interactive: bool = "interactive" in mode
        self.multi_pass: bool = "multi-pass" in mode
        self.custom_output: bool = (
            self.interactive
            or self.multi_pass
            or (problem.path / OutputValidator.source_dir).is_dir()
        )

        names: dict[object, object] = parser.extract("name", {"en": ""})
        self.name: dict[str, str] = {}
        for lang, name in names.items():
            if not isinstance(lang, str):
                parser.bar.warn(f"invalid language `{lang}` for `name` in problem.yaml. SKIPPED.")
            elif not isinstance(name, str):
                parser.bar.warn(
                    f"incompatible value for language `{lang}` for `name` in problem.yaml. SKIPPED."
                )
            else:
                self.name[lang] = name

        self.uuid: str = parser.extract("uuid", "")
        self.version: str = parser.extract("version", "")
        self.credits: ProblemCredits = ProblemCredits(parser)
        self.source: ProblemSources = ProblemSources(parser)
        self.license: str = parser.extract("license", "unknown")
        self.rights_owner: Optional[str] = parser.extract_optional("rights_owner", str)
        # Not implemented in BAPCtools. Should be a date, but we don't do anything with this anyway.
        # Note that datetime.datetime is also valid, as subclass of datetime.date
        self.embargo_until: Optional[datetime.date] = parser.extract_optional(
            "embargo_until", datetime.date
        )
        self.limits = ProblemLimits(parser.extract_parser("limits"), problem, self)

        parser.extract_deprecated(
            "validator_flags",
            f"{OutputValidator.args_key}' in 'test_group.yaml",
        )

        self.keywords: list[str] = parser.extract_optional_list("keywords", str, allow_empty=True)
        known_keywords = keywords()
        seen_keywords = set()
        for keyword in self.keywords:
            match = known_keywords.find(keyword)
            if keyword in seen_keywords:
                parser.bar.warn(f"found duplicate keyword {keyword}.")
            elif match:
                parser.bar.warn(f"found keyword {keyword}. Did you mean {match}?")
            seen_keywords.add(keyword)

        # an empty list means no restrction
        if parser.remaining.get("languages", None) == "all":
            parser.pop("languages")
        self.languages: list[str] = parser.extract_optional_list(
            "languages", str, allow_empty=False
        )

        # Not implemented in BAPCtools
        self.allow_file_writing: bool = parser.extract("allow_file_writing", False)

        constants: dict[object, object] = parser.extract("constants", {})
        self.constants: dict[str, str] = {}
        for key, value in constants.items():
            if not isinstance(key, str) or not config.CONSTANT_NAME_REGEX.fullmatch(key):
                parser.bar.warn(f"invalid name `{key}` for `constants` in problem.yaml. SKIPPED.")
                continue

            variants = set()
            if not isinstance(value, dict):
                value = {"value": value}
            if "value" not in value:
                parser.bar.warn(
                    f"missing `value` for key `constants.{key}` in problem.yaml. SKIPPED."
                )
                continue
            for sub, variant in value.items():
                if sub == "value" and isinstance(variant, (int, float)):
                    variant = str(variant)

                if not isinstance(sub, str):
                    parser.bar.warn(
                        f"invalid key `constants.{key}.{sub}` in problem.yaml. SKIPPED."
                    )
                elif not config.CONSTANT_NAME_REGEX.fullmatch(sub):
                    parser.bar.warn(
                        f"invalid key `constants.{key}.{sub}` in problem.yaml. SKIPPED."
                    )
                elif isinstance(variant, (int, float)):
                    parser.bar.warn(
                        f"invalid type {type(variant).__name__} for `constants.{key}.{sub}` in problem.yaml, use string. SKIPPED."
                    )
                elif not isinstance(variant, str):
                    parser.bar.warn(
                        f"invalid type for `constants.{key}.{sub}` in problem.yaml. SKIPPED."
                    )
                else:
                    variants.add(variant)
                    self.constants[f"{key}.{sub}"] = variant
                    if sub == "value":
                        self.constants[key] = variant

            # check if all variants represent the same value
            variant_numbers = {}
            for variant in variants:
                normalized = variant
                normalized = re.sub(
                    r"\\frac{(.*)}{(.*)}", r"(\1)/(\2)", normalized
                )  # LaTeX fraction
                normalized = normalized.replace("\\cdot{}", "*")  # LaTeX mul
                normalized = normalized.replace("\\cdot", "*")  # LaTeX mul
                normalized = normalized.replace("^", "**")  # latex pow
                normalized = normalized.replace("\\,", "")  # latex half space
                normalized = normalized.replace("_", "")  # python separator
                normalized = normalized.replace("'", "")  # c++ separator

                value = math_eval(normalized)
                if value is not None:
                    variant_numbers[(value, type(value))] = variant

            # TODO: consider float values with an eps?
            #      (compare the largest and smallest found float with rel/abs error)
            if len(variant_numbers) > 1:
                parser.bar.warn(
                    f"found different variants for {key}: {', '.join(variant_numbers.values())}"
                )

        # BAPCtools extensions:
        self.verified: Optional[str] = parser.extract_optional("verified", str)
        self.comment: Optional[str] = parser.extract_optional("comment", str)
        self.ans_is_output: bool = parser.extract(
            "ans_is_output", not self.interactive and not self.multi_pass
        )
        if (self.interactive or self.multi_pass) and self.ans_is_output:
            parser.bar.warn(
                f"ans_is_output: True makes no sense for {self.type_name()} problem. IGNORED."
            )
            self.ans_is_output = False

        parser.check_unknown_keys()

        # checks
        if not is_uuid(self.uuid):
            parser.bar.warn(f"invalid uuid: {self.uuid}")
        if self.license not in config.KNOWN_LICENSES:
            parser.bar.warn(f"invalid license: {self.license}")
            self.license = "unknown"
        if self.license == "public domain":
            if self.rights_owner is not None:
                parser.bar.warn(
                    f"problem cannot have license 'public domain' and have a rights owner: {self.rights_owner}"
                )
        elif self.license != "unknown":
            if self.rights_owner is None and not self.credits.authors and not self.source:
                parser.bar.warn(
                    f"problem with license '{self.license}': needs a rights owner, author, or source."
                )

    def type_name(self) -> str:
        parts: list[str] = []
        if self.interactive:
            parts.append("interactive")
        if self.multi_pass:
            parts.append("multi_pass")
        if not parts:
            parts.append("pass-fail")
        return " ".join(parts)


# A problem.
class Problem:
    SHORTNAME_REGEX: Final[re.Pattern[str]] = re.compile("[a-z0-9]{1,255}")

    def __init__(self, path: Path, tmpdir: Path, label: Optional[str] = None):
        # The problem name/shortname, which is the name of the directory and used as a display name.
        self.name = path.name
        # The Path of the problem directory.
        self.path = path
        self.tmpdir: Path = tmpdir / self.name
        self.tmpdir.mkdir(parents=True, exist_ok=True)

        bar = PrintBar(self.name)
        if not self.path.is_dir():
            bar.fatal("problem directory not found")
        if not Problem.SHORTNAME_REGEX.fullmatch(self.name):
            bar.warn(f"name does not match {Problem.SHORTNAME_REGEX.pattern}")

        # Read problem.yaml and domjudge-problem.ini into self.settings Namespace object.
        self._read_settings(bar)

        # Some caches.
        self._validators_warn_cache = set[tuple[type[AnyValidator], bool]]()
        self.programs = dict[Path, "Program"]()
        self.program_callbacks = defaultdict[Path, list[Callable[["Program"], None]]](list)

        self._root_test_group_yaml: Optional[TestGroup] = None
        # Dictionary from path to parsed file contents.
        self._test_group_yamls = dict[Path, TestGroup]()
        self._test_group_lock = threading.Lock()

        # The label for the problem: A, B, A1, A2, X, ...
        self.label = label

        self.statement_languages = self._determine_statement_languages(bar)

        for d in ["invalid_inputs", "invalid_answers", "invalid_outputs", "valid_outputs"]:
            if (self.path / "data" / d).is_dir():
                warn(f"Found directory: data/{d}, should be: data/{d[:-1]} (singular form).")

    def _determine_statement_languages(self, bar: BAR_TYPE) -> list[str]:
        """Determine the languages that are both mentioned in the problem.yaml under name
        and have a corresponding problem statement.

        If problem.yaml's name key is a string, convert into dict; assume `en` as default language.
        """
        yamllangs = set(self.settings.name)
        texlangs = set(
            path.suffixes[0][1:] for path in glob(self.path, str(latex.PdfType.PROBLEM.path("*")))
        )
        for lang in texlangs - yamllangs:
            bar.error(
                f"{self.name}: Found {latex.PdfType.PROBLEM.path(lang).name}, but no corresponding name in problem.yaml."
            )
        for lang in yamllangs - texlangs:
            bar.error(
                f"{self.name}: Found name for language {lang} in problem.yaml, but not {latex.PdfType.PROBLEM.path(lang)}."
            )
        # Check that names in problem.yaml and \problemname{} in problem.*.tex agree:
        for lang in texlangs & yamllangs:
            unnormalised_yamlname = self.settings.name[lang]
            yamlname = " ".join(unnormalised_yamlname.split())
            texpath = self.path / latex.PdfType.PROBLEM.path(lang)
            with texpath.open() as texfile:
                match texname := latex.get_argument_for_command(texfile, "problemname"):
                    case None:
                        bar.error(rf"No \problemname found in {texpath.name}")
                        continue
                    case "":
                        continue
                    case r"\problemyamlname":
                        bar.warn(
                            rf"Prefer using \problemname{{}} instead of \problemname{{\problemyamlname}} in {texpath.name}"
                        )
                        continue
                    case s if "\\" in s or "_" in s or "^" in s:
                        # texname contains markup, like "CO_2" or "\emph{Hello}":
                        # Assume authors know what they're doing
                        continue
                    case s if s != yamlname:
                        bar.warn(
                            f"Problem titles in {texpath.name} ({texname})"
                            + f" and problem.yaml ({yamlname}) differ;"
                            + r" consider using \problemname{}."
                        )
        return sorted(texlangs & yamllangs)

    def _read_settings(self, bar: BAR_TYPE) -> None:
        # parse problem.yaml
        yaml_path = self.path / "problem.yaml"
        try:
            yaml_data = read_yaml(yaml_path, empty={})
        except ScannerError:
            bar.fatal(f"Make sure {self.name}/problem.yaml does not contain any more {{% ... %}}.")

        if not isinstance(yaml_data, dict):
            bar.fatal(f"{self.name}/problem.yaml is illformed.")

        if "uuid" not in yaml_data:
            uuid = generate_problem_uuid()
            yaml_data["uuid"] = uuid
            raw = yaml_path.read_text().rstrip()
            raw += f"\n# uuid added by BAPCtools\nuuid: '{uuid}'\n"
            yaml_path.write_text(raw)
            bar.log("Added new UUID to problem.yaml")

        parser = YamlParser("problem.yaml", yaml_data, bar=bar)
        self.settings = ProblemSettings(parser, self)

        # Aliasing fields makes life easier for us 😛
        self.limits: ProblemLimits = self.settings.limits
        self.interactive: bool = self.settings.interactive
        self.multi_pass: bool = self.settings.multi_pass
        self.custom_output: bool = self.settings.custom_output

    def register_program_callback(self, path: Path, c: Callable[["Program"], None]) -> None:
        self.program_callbacks[path].append(c)

    def get_test_group_yaml(self, path: Path, bar: BAR_TYPE) -> TestGroup:
        """
        Find the test_group.yaml for the given path.
        If necessary, walk up from `path` looking for the first test_group.yaml file that applies.

        Side effects: parses and caches the file.

        Arguments
        ---------
        path: absolute path (a <test_case>.yaml file or a test group directory)

        Returns:
        --------
        A TestGroup object
        """
        assert path.is_relative_to(self.path / "data"), f"{path} is not in data"

        paths = []
        for f in [path, *path.parents]:
            # ignore <test_case>.yaml
            if f.is_file():
                continue
            # Do not go above the data directory.
            if f == self.path:
                break
            paths.append(f)

        # create a root TestGroup object
        if self._root_test_group_yaml is None:
            with self._test_group_lock:
                if self._root_test_group_yaml is None:
                    self._root_test_group_yaml = TestGroup(self, None, {}, None, bar)

        test_group_yaml = self._root_test_group_yaml
        for f in reversed(paths):
            f = f / "test_group.yaml"
            if not f.is_file():
                continue
            if f not in self._test_group_yamls:
                with self._test_group_lock:
                    # handle race conditions
                    if f not in self._test_group_yamls:
                        parsed = TestGroup.parse_yaml(self, f, test_group_yaml, bar)
                        self._test_group_yamls[f] = parsed
            assert f in self._test_group_yamls
            test_group_yaml = self._test_group_yamls[f]
        return test_group_yaml

    @once_per_instance
    def _warn_once(self, test_name: str, msg: str) -> None:
        # Because Problem.test_cases() may be called multiple times (e.g. validating multiple modes, or with `bt all`),
        # this cache makes sure that some warnings (like malformed test case names) only appear once.
        warn(msg)

    def _valid_test_group(self, path: Path) -> bool:
        for group in reversed(path.parents[:-1]):
            if not config.FILE_NAME_REGEX.fullmatch(group.name):
                self._warn_once(
                    group.as_posix(), f"Test group name {group.name} is not valid. Skipping."
                )
                return False
        return True

    def test_cases(
        self,
        *,
        mode: Optional[validate.Mode] = None,
        needans: bool = True,
        only_samples: bool = False,
        testing_tool_test: bool = False,
    ) -> Sequence[TestCase]:
        return self._test_cases(
            mode=mode,
            needans=needans,
            only_samples=config.args.samples or only_samples,
            testing_tool_test=testing_tool_test,
        )

    @once_per_instance
    def _test_cases(
        self,
        *,
        mode: Optional[validate.Mode],
        needans: bool,
        only_samples: bool,
        testing_tool_test: bool,
    ) -> Sequence[TestCase]:
        in_paths = None
        if config.args.test_cases:
            assert not only_samples
            # Deduplicate test cases with both .in and .ans.
            in_paths = []
            for path in config.args.test_cases:
                res_path = resolve_path_argument(self, path, "data", suffixes=[".in"])
                if res_path:
                    # When running from contest level, the test case must be inside the problem.
                    if config.level != "problemset" or res_path.is_relative_to(self.path):
                        if res_path.is_dir():
                            in_paths += glob(res_path, "**/*.in")
                        else:
                            in_paths.append(res_path)

            in_paths = list(set(in_paths))
        elif mode is not None:
            assert not only_samples
            assert not testing_tool_test
            assert needans
            in_paths = []
            for prefix in {
                validate.Mode.INPUT: ["secret", "sample"],
                validate.Mode.ANSWER: ["secret", "sample"],
                validate.Mode.INVALID: config.INVALID_CASE_DIRECTORIES,
                validate.Mode.VALID_OUTPUT: ["secret", "sample", "valid_output"],
            }[mode]:
                in_paths += glob(self.path, f"data/{prefix}/**/*.in")
        elif testing_tool_test:
            in_paths = list(glob(self.path, "data/testing_tool_test/**/*.in"))
        else:
            in_paths = list(glob(self.path, "data/sample/**/*.in"))
            if not only_samples:
                in_paths += list(glob(self.path, "data/secret/**/*.in"))

        test_cases = []
        for f in in_paths:
            t = TestCase(self, f)
            if not self._valid_test_group(t.short_path):
                continue
            if not config.FILE_NAME_REGEX.fullmatch(f.name):
                self._warn_once(t.name, f"Test case name {t.name} is not valid. Skipping.")
                continue
            if f.with_suffix("").name == "test_group":
                self._warn_once(
                    t.name,
                    "Test case must not be named 'test_group', this clashes with the group-level 'test_group.yaml'. Skipping.",
                )
                continue
            if (
                (self.interactive or self.multi_pass)
                and mode in [validate.Mode.INVALID, validate.Mode.VALID_OUTPUT]
                and t.root in ["invalid_output", "valid_output"]
            ):
                self._warn_once(
                    t.name,
                    f"Found file {f} for {mode} validation in {self.settings.type_name()} problem. Skipping.",
                )
                continue
            if needans and not t.ans_path.is_file():
                if t.root != "invalid_input":
                    self._warn_once(t.name, f"Found input file {f} without a .ans file. Skipping.")
                    continue
            if t.root in ["valid_output", "invalid_output"]:
                assert t.out_path is not None
                if not t.out_path.is_file():
                    self._warn_once(t.name, f"Found input file {f} without a .out file. Skipping.")
                    continue
            if mode == validate.Mode.VALID_OUTPUT:
                if t.out_path is None:
                    continue
                if not t.out_path.is_file():
                    warn(f"Found input file {f} without a .out file. Skipping.")
                    continue
            test_cases.append(t)
        test_cases.sort(key=lambda t: t.name)

        if len(test_cases) == 0 and not testing_tool_test:
            ans = (
                " with answer"
                if needans and mode not in [validate.Mode.INVALID, validate.Mode.VALID_OUTPUT]
                else ""
            )
            val = f" for {mode} validation" if mode is not None else ""
            # TODO perhaps move this log to the use site?
            (log if mode in [validate.Mode.INVALID, validate.Mode.VALID_OUTPUT] else warn)(
                f"Didn't find any test cases{ans}{val} in problem {self.name}. Skipping."
            )

        return tuple(test_cases)

    @once_per_instance
    def overrides(self, *, only_samples: bool = False) -> Sequence[TestCaseOverrides]:
        """
        Find the test case overrides of the problem

        Returns:
        --------
        A list of TestCaseOverrides. The TestCaseOverrides contains separate data for statement and download.
        The entries sample is represented bei either a (.in, .ans) tuple or (only for statement) a .interaction file
        """

        in_extensions = [
            ".in.statement",
            ".in.download",
            ".in",
        ]
        ans_extensions = [
            ".ans.statement",
            ".ans.download",
            ".out",
            ".ans",
        ]

        files: set[Path] = set()
        dirs = ["sample"] if only_samples else ["sample", "secret"]
        for prefix in dirs:
            for ext in [".in", ".in.statement", ".interaction"]:
                for file in glob(self.path, f"data/{prefix}/**/*{ext}"):
                    if not file.is_file():
                        continue
                    base = drop_suffix(file, [ext])
                    # add .in to make .with_suffix() work
                    files.add(base.with_name(base.name + ".in"))
        overrides = []

        has_raw = False
        for file in files:
            name = file.with_suffix("").relative_to(self.path / "data").as_posix()
            in_found = [ext for ext in in_extensions if file.with_suffix(ext).is_file()]
            ans_found = [ext for ext in ans_extensions if file.with_suffix(ext).is_file()]
            has_override = len(in_found) == 0 and len(ans_found) == 0

            statement: Optional[tuple[Path, Path] | tuple[Path]] = None
            download: Optional[tuple[Path, Path]] = None

            # overrides are only defined for samples
            if has_override and not file.is_relative_to(self.path / "data" / "sample"):
                warn(f"Found override for non sample file: {name}")

            # check for inconsistencies
            if ".in" in in_found and ".ans" not in ans_found:
                warn(f"Found {name}.in but no {name}.ans. SKIPPING.")
                continue

            # resolve some inconsistencies
            if ".in" not in in_found:
                if ".ans" in ans_found:
                    warn(f"Found {name}.ans but no {name}.in. IGNORED.")
                    ans_found.remove(".ans")
                if ".out" in ans_found:
                    warn(f"Found {name}.out but no {name}.in. IGNORED.")
                    ans_found.remove(".out")
            if ".ans.statement" in ans_found and ".out" in ans_found:
                # we prefer .statement files
                warn(f"Found {name}.out (but also .statement). IGNORED.")
                ans_found.remove(".out")

            # .interaction files get highest priority
            if file.with_suffix(".interaction").is_file():
                if not self.interactive and not self.multi_pass:
                    warn(
                        f"Found {name}.interaction for non-interactive/non-multi-pass problem. IGNORED."
                    )
                else:
                    if ".in.statement" in in_found or ".ans.statement" in ans_found:
                        warn(
                            f"Mixed .interaction and .statement file for {name}. (using .interaction)."
                        )
                    if ".out" in ans_found:
                        warn(f"Mixed .interaction and .out file for {name}. (using .interaction).")
                statement = (file.with_suffix(".interaction"),)
            else:
                statement_in = [ext for ext in in_found if not ext.endswith(".download")]
                statement_ans = [ext for ext in ans_found if not ext.endswith(".download")]
                if statement_in and statement_ans:
                    statement = (
                        file.with_suffix(statement_in[0]),
                        file.with_suffix(statement_ans[0]),
                    )

            download_in = [ext for ext in in_found if not ext.endswith(".statement")]
            download_ans = [ext for ext in ans_found if not ext.endswith(".statement")]
            if download_in and download_ans:
                download = (file.with_suffix(download_in[0]), file.with_suffix(download_ans[0]))

            if not statement or not download:
                warn(f"Could not find valid .in/.ans combination for test case {name}. SKIPPED.")
                continue

            if (statement[0].suffix == ".in") != (download[0].suffix == ".in"):
                warn("You are supposed to override .in for statement and download. SKIPPED.")
                continue
            if (statement[-1].suffix == ".in") != (download[-1].suffix == ".in"):
                warn("You are supposed to override .ans for statement and download. SKIPPED.")
                continue

            if statement[-1].suffix == ".ans" and statement[-1].stat().st_size > 0:
                has_raw = True
            if download[-1].suffix == ".ans" and download[-1].stat().st_size > 0:
                has_raw = True

            overrides.append(
                TestCaseOverrides(name, statement if len(statement) > 1 else statement[0], download)
            )

        if has_raw and not self.settings.ans_is_output and only_samples:
            warn(
                "It is advised to override .ans for samples if it does not represent a valid output."
                + "\n\tUse .ans.statement+.ans.download or .out for this."
            )

        overrides.sort(key=lambda t: t.name)
        return tuple(overrides)

    # Returns the list of submissions passed as command-line arguments, or the list of accepted submissions by default.
    def selected_or_accepted_submissions(self) -> Sequence[Submission]:
        submissions = self.submissions()
        if config.args.submissions:
            return submissions
        else:
            return tuple(s for s in submissions if s.expectations.is_accepted())

    @once_per_instance
    def expectations(self) -> Expectations:
        return Expectations(self)

    # Returns a list of all submissions the submissions might or might not have already
    # been compiled depending on other calls
    # No function except problem.submissions() should attempt to build these!
    @once_per_instance
    def raw_submissions(self) -> Sequence[Submission]:
        # ensure that expectations are cached
        self.expectations()

        paths = []
        if config.args.submissions:

            def add(s: Path) -> None:
                if s in paths:
                    warn(f"Ignoring duplicate submission: {s}")
                    return
                paths.append(s)

            for submission in config.args.submissions:
                s = resolve_path_argument(self, submission, "submissions")
                if s:
                    if s == self.path / "submissions":
                        paths += glob(s, "*/*")
                    elif s.parent == self.path / "submissions":
                        for s in glob(s, "*"):
                            add(s)
                    else:
                        # If running from a contest, the submission must be inside a problem.
                        if config.level == "problem" or s.is_relative_to(self.path):
                            add(s)
        else:
            for s in glob(self.path / "submissions", "*/*"):
                if (
                    s.parent.name == "time_limit_exceeded"
                    and config.RUNNING_TEST
                    and not config.TEST_TLE_SUBMISSIONS
                ):
                    continue

                paths.append(s)

        if len(paths) == 0:
            error("No submissions found!")
            return tuple()

        def submissions_key(x: Submission) -> tuple[int, str, str]:
            order = [
                "accepted",
                "wrong_answer",
                "brute_force",
                "time_limit_exceeded",
                "run_time_error",
                None,
                "rejected",
            ]
            group = "accepted" if x.expectations.is_accepted() else x.subdir
            group_key = order.index(group if group in order else None)
            return group_key, x.subdir, x.name

        programs = [Submission(self, path) for path in paths]
        programs.sort(key=submissions_key)
        return tuple(programs)

    @once_per_instance
    def submissions(self) -> Sequence[Submission]:
        programs = self.raw_submissions()

        bar = ProgressBar("Build submissions", items=programs)

        def build_program(p: Submission) -> None:
            localbar = bar.start(p)
            p.build(localbar)
            localbar.done()

        parallel.run_tasks(build_program, programs)

        bar.finalize(print_done=False)

        # Filter out broken submissions.
        return tuple(p for p in programs if p.ok)

    @overload
    @once_per_instance
    def visualizer(self, cls: type[InputVisualizer]) -> Optional[InputVisualizer]: ...
    @overload
    @once_per_instance
    def visualizer(self, cls: type[OutputVisualizer]) -> Optional[OutputVisualizer]: ...
    @once_per_instance
    def visualizer(self, cls: type[AnyVisualizer]) -> Optional[AnyVisualizer]:
        path = self.path / cls.source_dir
        if not path.is_dir():
            return None
        visualizer = cls(self, path)
        bar = ProgressBar(f"Building {cls.visualizer_type} visualizer", items=[visualizer])
        localbar = bar.start(visualizer)
        visualizer.build(localbar)
        localbar.done()
        bar.finalize(print_done=False)
        return visualizer if visualizer.ok else None

    def output_validator(self) -> Optional[OutputValidator]:
        output_validators = self.validators(OutputValidator)
        if not output_validators:
            return None
        assert len(output_validators) == 1
        output_validator = output_validators[0]
        assert isinstance(output_validator, OutputValidator)
        return output_validator

    def validators(
        self,
        cls: type[AnyValidator],
        check_constraints: bool = False,
        strict: bool = False,
        print_warn: bool = True,
    ) -> Sequence[AnyValidator]:
        """
        Gets the validators of the given class.
        If strict is true we only return the validators as the icpc specification indicates.
        If strict is false we may return additional validators (right now we return OutputValidators as AnswerValidators).

        If needed, builds them.

        Returns:
            singleton list(OutputValidator) if cls is OutputValidator
            list(Validator) otherwise, maybe empty
        """
        validators = self._validators(cls, check_constraints)
        if not strict and cls == AnswerValidator and self.settings.ans_is_output:
            validators = (
                *validators,
                *self._validators(OutputValidator, check_constraints),
            )

        # Check that the proper number of validators is present
        # do this after handling the strict flag but do not warn every time
        if print_warn:
            key = (cls, check_constraints)
            if key not in self._validators_warn_cache:
                constraints_msg = " for constraints checking" if check_constraints else ""
                self._validators_warn_cache.add(key)
                if cls == InputValidator and not validators:
                    warn(f"No input validators{constraints_msg} found.")
                if cls == AnswerValidator and not validators and not self.interactive:
                    # for interactive problems, the .ans file should be empty
                    warn(f"No answer validators{constraints_msg} found.")

        build_ok = all(v.ok for v in validators)

        # All validators must build.
        # TODO Really? Why not at least return those that built?
        return validators if build_ok else tuple()

    @once_per_instance
    def _validators(
        self, cls: type[AnyValidator], check_constraints: bool = False
    ) -> Sequence[AnyValidator]:
        if cls == OutputValidator:
            if self.custom_output:
                paths = [self.path / OutputValidator.source_dir]
            else:
                paths = [config.RESOURCES_ROOT / "support" / "default_output_validator.cpp"]
        else:
            paths = list(glob(self.path / cls.source_dir, "*"))

        # TODO: Instead of checking file contents, maybe specify this in generators.yaml?
        def has_constraints_checking(f: Path) -> bool:
            if not f.is_file():
                return False
            if f.suffix == ".ctd":
                return True
            try:
                return "constraints_file" in f.read_text()
            except UnicodeDecodeError:
                return False

        if check_constraints:
            paths = [
                f
                for f in paths
                if any(
                    has_constraints_checking(source)
                    for source in ([f] if f.is_file() else glob(f, "**/*"))
                )
            ]

        skip_double_build_warning = (
            check_constraints  # or not paths_for_class[Class.ANSWER] TODO not sure about this
        )
        validators = tuple(
            cls(
                self,
                path,
                skip_double_build_warning=skip_double_build_warning,
                check_constraints=check_constraints,
            )
            for path in paths
        )
        bar = ProgressBar(f"Building {cls.validator_type} validator", items=validators)

        def build_program(p: "Program") -> None:
            localbar = bar.start(p)
            p.build(localbar)
            localbar.done()

        parallel.run_tasks(build_program, validators)
        bar.finalize(print_done=False)
        return validators

    # get all test cases and submissions and prepare the output validator and visualizer
    def prepare_run(self) -> Literal[False] | tuple[Sequence[TestCase], Sequence[Submission]]:
        test_cases = self.test_cases()
        if not test_cases:
            return False

        # Pre build the output validator to prevent nested ProgressBars.
        if not self.output_validator():
            return False

        # Pre build the output visualizer to prevent nested ProgressBars.
        if not config.args.no_visualizer:
            self.visualizer(OutputVisualizer)

        submissions = self.submissions()
        if not submissions:
            return False

        return test_cases, submissions

    @staticmethod
    def run_some(
        test_cases: Sequence[TestCase],
        submissions: Sequence[Submission],
        skip_test_case: Callable[[Submission, TestCase], bool] = lambda s, t: False,
    ) -> tuple[bool, verdicts.VerdictTable]:
        max_submission_len = max([len(x.name) for x in submissions])

        ok = True
        verdict_table = verdicts.VerdictTable(submissions, test_cases)
        # When true, the ProgressBar will print a newline before the first error log.
        needs_leading_newline = False if config.args.verbose else True
        for submission in submissions:
            submission_ok, printed_newline = submission.run_test_cases(
                max_submission_len,
                verdict_table,
                test_cases,
                skip_test_case,
                needs_leading_newline=needs_leading_newline,
            )
            needs_leading_newline = not printed_newline
            ok &= submission_ok
        return ok, verdict_table

    def run_until(self) -> verdicts.RunUntil:
        if config.args.all == 2 or config.args.reorder:
            return verdicts.RunUntil.ALL
        if (
            config.args.all == 1
            or config.args.verbose
            or config.args.action in ["all", "time_limit"]
        ):
            return verdicts.RunUntil.DURATION
        return verdicts.RunUntil.FIRST_ERROR

    # called by bt run
    def run_submissions(self) -> bool:
        ts_pair = self.prepare_run()
        if not ts_pair:
            return False
        test_cases, submissions = ts_pair

        msg = (
            "localy adjusted "
            if config.args.local_time_multiplier is not None and config.args.time_limit is None
            else ""
        )
        bar = PrintBar("Run")
        bar.log(f"using {msg}timelimit: {self.limits.time_limit:.1f}s\n", color="")

        ok, verdict_table = Problem.run_some(test_cases, submissions)

        if (
            len(test_cases) * len(submissions) > 1
            and not config.args.verbose
            and not config.args.no_visualizer
            and self.visualizer(OutputVisualizer)
        ):
            log("use -v with --visualize to see the paths to the generated images")

        if config.args.overview and not config.args.tree:
            verdict_table.print(new_lines=1)

        if self.run_until() in [verdicts.RunUntil.DURATION, verdicts.RunUntil.ALL]:
            time_sensitive_lower = self.limits.time_limit / self.limits.ac_to_time_limit
            time_sensitive_upper = self.limits.time_limit * self.limits.time_limit_to_tle
            time_sensitive = False
            for row in verdict_table.results:
                durations = [d for d in row.duration.values() if d is not None]
                if durations:
                    time_sensitive |= time_sensitive_lower < max(durations) < time_sensitive_upper
            if time_sensitive:
                bar.warn(
                    f"Some submissions are sensitive to timelimit (between {time_sensitive_lower:.1f}s and {time_sensitive_upper:.1f}s)"
                )

        if config.args.table:
            Problem._print_table(verdict_table.results, test_cases)

        return ok

    # Takes a list of submissions and runs them against the chosen test cases.
    # Instead of validating the output, this function just prints all output to the
    # terminal.
    # Note: The CLI only accepts one submission.
    def test_submissions(self) -> bool:
        submissions = self.submissions()
        if not submissions:
            return False

        for submission in submissions:
            if config.args.interactive:
                submission.test_interactive()
            else:
                submission.test()
        return True

    @staticmethod
    def _print_table(
        verdict_table: Sequence[verdicts.Verdicts], test_cases: Sequence[TestCase]
    ) -> None:
        # Begin by aggregating bitstrings for all test cases, and find bitstrings occurring often (>=config.TABLE_THRESHOLD).
        def single_verdict(row: verdicts.Verdicts, test_case: TestCase) -> str:
            assert row[test_case.name] is not None
            if row[test_case.name] is not False:
                return verdicts.to_char(row[test_case.name])
            else:
                return f"{Style.DIM}-{Style.RESET_ALL}"

        def make_verdict(tc: TestCase) -> str:
            return "".join(map(lambda row: single_verdict(row, tc), verdict_table))

        resultant_count, resultant_id = dict[str, int](), dict[str, int]()
        special_id = 0
        for case in test_cases:
            resultant = make_verdict(case)
            if resultant not in resultant_count:
                resultant_count[resultant] = 0
            resultant_count[resultant] += 1
            if resultant_count[resultant] == config.TABLE_THRESHOLD:
                special_id += 1
                resultant_id[resultant] = special_id

        scores = dict[str, float]()
        for t in test_cases:
            scores[t.name] = 0
        for dct in verdict_table:
            failures = 0
            for t in test_cases:
                if dct[t.name] != verdicts.Verdict.ACCEPTED:
                    failures += 1
            for t in test_cases:
                if dct[t.name] != verdicts.Verdict.ACCEPTED:
                    scores[t.name] += 1.0 / failures
        scores_list = sorted(scores.values())

        eprint(
            "\nVerdict analysis table. Submissions are ordered per column as above. Higher "
            "scores indicate they are critical to break some submissions. Only cases breaking at least one submission are listed."
        )
        fail = (
            verdicts.to_char(verdicts.Verdict.WRONG_ANSWER)
            + verdicts.to_char(verdicts.Verdict.TIME_LIMIT_EXCEEDED)
            + verdicts.to_char(verdicts.Verdict.RUNTIME_ERROR)
        )
        eprint(f"{fail}: submission fails test case")
        eprint(f"{verdicts.to_char(verdicts.Verdict.ACCEPTED)}: submission passes test case\n")

        name_col_width = min(50, max([len(test_case.name) for test_case in test_cases]))

        for case in test_cases:
            # Skip all AC test cases
            if all(
                map(
                    lambda row: row[case.name] == verdicts.Verdict.ACCEPTED,
                    verdict_table,
                )
            ):
                continue

            name = case.name
            if len(name) > name_col_width:
                name = "..." + name[-name_col_width + 3 :]
            padding = " " * (name_col_width - len(name))
            eprint(f"{Fore.CYAN}{name}{Style.RESET_ALL}:{padding}", end=" ")

            color = Style.RESET_ALL
            if len(scores_list) > 6 and scores[case.name] >= scores_list[-6]:
                color = Fore.YELLOW
            if len(scores_list) > 3 and scores[case.name] >= scores_list[-3]:
                color = Fore.RED
            resultant = make_verdict(case)
            eprint(resultant, end="  ")
            eprint(f"{color}{scores[case.name]:0.3f}{Style.RESET_ALL}  ", end="")
            if resultant in resultant_id:
                eprint(f"(Type {resultant_id[resultant]})", end="")
            eprint()

    # called by bt check_testing_tool
    def check_testing_tool(self) -> bool:
        test_cases = self.test_cases(needans=False, testing_tool_test=True)
        testinputs = [
            check_testing_tool.TestInput(self, t.in_path, t.short_path) for t in test_cases
        ]
        if not config.args.test_cases:
            sampleinputs = []
            for sample in self.overrides(only_samples=True):
                in_path = sample.download[0]
                sampleinput = check_testing_tool.TestInput(
                    self, in_path, in_path.relative_to(self.path / "data")
                )
                if sampleinput not in testinputs:
                    sampleinputs.append(sampleinput)
            testinputs = sampleinputs + testinputs
        if not testinputs:
            warn(
                f"Didn't find any test cases to run the testing tool in problem {self.name}. Skipping."
            )
            return False
        submissions = self.selected_or_accepted_submissions()
        if not submissions:
            return False
        return check_testing_tool.run(self, testinputs, submissions)

    def reset_test_case_hashes(self) -> None:
        self._test_case_hashes: dict[str, TestCase] = {}

    # Returns None for new test_cases or the TestCase object it equals.
    def matches_existing_test_case(self, t: TestCase, bar: BAR_TYPE) -> Optional[TestCase]:
        h = t.core_hash(bar)
        if h in self._test_case_hashes:
            return self._test_case_hashes[h]
        self._test_case_hashes[h] = t
        return None

    def check_output_validator(self) -> bool:
        assert config.args.generic is not None
        if "invalid_output" not in config.args.generic:
            return True
        if not self.interactive and not self.multi_pass:
            # standart problems can just use valid_output
            return True

        # pick at most first 3 samples (assuming they are valid and have .ans)
        samples = sorted(glob(self.path, "data/sample/**/*.in"))
        samples = [s for s in samples if s.with_suffix(".ans").exists()]
        samples = samples[:3]

        base_path = self.tmpdir / "invalid_data" / "output_validator_checks"
        test_cases = []
        for i, sample in enumerate(samples):
            for name, data, supported_cls in validator_tests.INVALID_GENERATORS:
                if OutputValidator not in supported_cls:
                    continue

                if not isinstance(data, str):
                    continue

                short_path = sample.relative_to(self.path / "data").with_suffix("") / name
                full_path = base_path / short_path / "testcase.in"
                remove_path(full_path.parent)
                full_path.parent.mkdir(parents=True, exist_ok=True)

                for ext in [".in", ".ans"]:
                    shutil.copy(sample.with_suffix(ext), full_path.with_suffix(ext))
                full_path.with_name("submission.out").write_text(data)

                verbose(f"Generating {short_path}")
                test_cases.append(TestCase(self, full_path, short_path=short_path))
        if not test_cases:
            return True

        # Pre-build the output validator
        output_validator = self.output_validator()
        if not output_validator:
            return False

        success = True
        bar = ProgressBar("Output Validator checks", items=test_cases)

        def run(test_case: TestCase) -> None:
            nonlocal success
            localbar = bar.start(test_case)

            submission = test_case.in_path.with_name("submission.out")
            raw_submission = submission.read_text()

            feedbackdir = submission.with_suffix(".feedbackdir")
            feedbackdir.mkdir(parents=True, exist_ok=True)
            nextpass = feedbackdir / "nextpass.in" if self.multi_pass else None
            for pass_id in itertools.count(1):
                ret = output_validator.run(test_case, submission)
                if self.interactive:
                    ret.out = None

                data = ""
                if config.args.error:
                    if ret.err and ret.out:
                        data = (
                            ret.err
                            + f"\n{Fore.RED}VALIDATOR STDOUT{Style.RESET_ALL}\n"
                            + Fore.YELLOW
                            + ret.out
                        )
                    elif ret.err:
                        data = ret.err
                    elif ret.out:
                        data = ret.out

                    data += f"{Style.RESET_ALL}-> {shorten_path(self, test_case.in_path.parent)}\n"
                elif ret.err:
                    data = ret.err

                if ret.status == ExecStatus.REJECTED:
                    if nextpass and nextpass.is_file():
                        success = False
                        localbar.error(
                            "Output Validator gave WRONG_ANSWER but created nextpass.in", data
                        )
                        return
                    else:
                        localbar.done(True, "rejected", data)
                        return
                if ret.status == ExecStatus.TIMEOUT:
                    localbar.error("Output Validator got TIMEOUT", data)
                    return
                if ret.status == ExecStatus.ERROR:
                    if ret.returncode == 0:
                        success = False
                        localbar.error(
                            "Output Validator exited with exit code 0, did you forget to exit with WA or AC?",
                            data,
                        )
                    else:
                        success = False
                        localbar.error(
                            f"Output Validator crashed (exit code: {ret.returncode})", data
                        )
                    return
                assert ret.status == ExecStatus.ACCEPTED
                if not nextpass or not nextpass.is_file():
                    localbar.error(
                        f"Output Validator did not reject submission only printing: {raw_submission}",
                        data,
                    )
                    return

                assert self.limits.validation_passes is not None
                if pass_id >= self.limits.validation_passes:
                    success = False
                    localbar.error("Output Validator exceeded limit of validation_passes", data)
                    return
                # use nextpass.in as input and check again
                shutil.move(nextpass, test_case.in_path)

        parallel.run_tasks(run, test_cases, pin=True)
        bar.finalize(print_done=True)
        return success

    def validate_data(
        self,
        mode: validate.Mode,
        constraints: Optional[ConstraintsDict | Literal[True]] = None,
    ) -> bool:
        """Validate aspects of the test data files.

        Arguments:
            mode: validate.Mode
            constraints: Optional[True | ConstraintsDict]. True means "do check constraints but discard the result."
        Return:
            True if all validation was successful. Successful validation includes, e.g.,
            correctly rejecting invalid inputs.
        """
        action: str = ""
        if mode == validate.Mode.INVALID:
            action = "Invalidation"
        elif mode == validate.Mode.VALID_OUTPUT:
            action = "Output validation"
        elif constraints is not None:
            action = f"Collecting {str(mode).capitalize()} constraints"
        else:
            action = f"{str(mode).capitalize()} validation"

        test_cases = self.test_cases(mode=mode)
        return self._validate_data(mode, constraints, action, test_cases)

    def validate_invalid_extra_data(self) -> bool:
        assert config.args.generic is not None
        base_path = self.tmpdir / "invalid_data"
        # pick at most first 3 samples (assuming they are valid and have .ans)
        # also add a dummy entry to always run generators that don't read or copy anything from a valid test case
        samples = sorted(glob(self.path, "data/sample/**/*.in"))[:3] + [None]

        # validator, dir, read, write, copy
        validators: list[tuple[type[AnyValidator], str, str, str, list[str]]] = [
            (InputValidator, "invalid_input", ".in", ".in", []),
            (AnswerValidator, "invalid_answer", ".ans", ".ans", [".in"]),
            (
                OutputValidator,
                "invalid_output",
                ".ans" if self.settings.ans_is_output else ".out",
                ".out",
                [".in", ".ans"],
            ),
        ]

        test_cases: list[TestCase] = []
        for i, sample in enumerate(samples):
            used_sample = False
            for cls, directory, read, write, copy in validators:
                if directory not in config.args.generic:
                    continue
                if self.interactive and cls != InputValidator:
                    continue
                if self.multi_pass and cls == OutputValidator:
                    continue
                if not self.validators(cls, strict=True, print_warn=False):
                    continue
                if any(sample is None or not sample.with_suffix(ext).exists() for ext in copy):
                    continue

                for name, data, supported_cls in validator_tests.INVALID_GENERATORS:
                    if cls not in supported_cls:
                        continue

                    if isinstance(data, str):
                        # generators that don't read or copy anything must only be run once
                        if i > 0 and not copy:
                            continue
                        content = data
                    elif sample is None:
                        continue
                    elif not sample.with_suffix(read).exists():
                        continue
                    else:
                        valid = sample.with_suffix(read).read_text()
                        generated = data(valid)
                        if generated is None:
                            continue
                        used_sample = True
                        content = generated

                    short_path = Path(directory) / str(i) / name
                    full_path = base_path / short_path / "testcase.in"
                    full_path.parent.mkdir(parents=True, exist_ok=True)

                    for ext in copy:
                        assert sample is not None
                        assert sample.with_suffix(ext).exists()
                        shutil.copy(sample.with_suffix(ext), full_path.with_suffix(ext))
                        used_sample = True
                    full_path.with_suffix(write).write_text(content)

                    verbose(f"Generating {short_path}")
                    test_cases.append(TestCase(self, full_path, short_path=short_path))
            if used_sample:
                assert sample is not None
                sample_name = sample.relative_to(self.path / "data").with_suffix("")
                log(f"Generated invalid test cases based on: {sample_name}")
        if test_cases:
            verbose(f"writing generated invalid test cases to: {base_path}")

        return self._validate_data(
            validate.Mode.INVALID, None, "Generic Invalidation", test_cases, True
        )

    def validate_valid_extra_data(self) -> bool:
        assert config.args.generic is not None
        if "valid_output" not in config.args.generic:
            return True
        if self.interactive or self.multi_pass:
            return True
        if not self.output_validator():
            return True

        args = self.get_test_group_yaml(
            self.path / "data" / "valid_output",
            PrintBar("Generic Output Validation"),
        ).output_validator_args
        is_space_sensitive = "space_change_sensitive" in args
        is_case_sensitive = "case_sensitive" in args

        base_path = self.tmpdir / "valid_data"
        # pick at most first 3 samples (assuming they are valid and have .ans)
        samples = sorted(glob(self.path, "data/sample/**/*.in"))
        samples = [s for s in samples if s.with_suffix(".ans").exists()]
        samples = samples[:3]

        test_cases: list[TestCase] = []
        for i, sample in enumerate(samples):
            used_sample = False
            for name, data, space_change, case_change in validator_tests.VALID_GENERATORS:
                if space_change and is_space_sensitive:
                    continue
                elif case_change and is_case_sensitive:
                    continue

                if isinstance(data, str):
                    content = data
                else:
                    valid = sample.with_suffix(".ans").read_text()
                    generated = data(valid)
                    if generated is None:
                        continue
                    content = generated

                used_sample = True
                short_path = Path("valid_output") / str(i) / name
                full_path = base_path / short_path / "testcase.in"
                full_path.parent.mkdir(parents=True, exist_ok=True)

                for ext in [".in", ".ans"]:
                    shutil.copy(sample.with_suffix(ext), full_path.with_suffix(ext))
                full_path.with_suffix(".out").write_text(content)

                verbose(f"Generating {short_path}")
                test_cases.append(TestCase(self, full_path, short_path=short_path))
            if used_sample:
                assert sample is not None
                sample_name = sample.relative_to(self.path / "data").with_suffix("")
                log(f"Generated valid test cases based on: {sample_name}")
        if test_cases:
            verbose(f"writing generated valid test cases to: {base_path}")

        return self._validate_data(
            validate.Mode.VALID_OUTPUT, None, "Generic Output Validation", test_cases, True
        )

    def _validate_data(
        self,
        mode: validate.Mode,
        constraints: Optional[ConstraintsDict | Literal[True]],
        action: str,
        test_cases: Sequence[TestCase],
        extra: bool = False,
    ) -> bool:
        # If there are no test cases, validation succeeds
        if not test_cases:
            return True

        constraints_dict = {} if constraints is True else constraints
        check_constraints = constraints_dict is not None

        # Pre-build the relevant Validators so as to avoid clash with ProgressBar bar below
        # Also, pick the relevant test cases
        match mode:
            case validate.Mode.INPUT:
                self.validators(InputValidator, check_constraints=check_constraints)
            case validate.Mode.ANSWER:
                self.validators(AnswerValidator, check_constraints=check_constraints)
            case validate.Mode.INVALID:
                self.validators(InputValidator)
                self.validators(AnswerValidator)
                self.validators(OutputValidator)
            case validate.Mode.VALID_OUTPUT:
                self.validators(InputValidator)
                self.validators(AnswerValidator)
                self.validators(OutputValidator)
            case _:
                raise ValueError(mode)

        success = True

        self.reset_test_case_hashes()

        # validate the test cases
        bar = ProgressBar(action, items=[t.name for t in test_cases])

        def process_test_case(test_case: TestCase) -> None:
            nonlocal success

            localbar = bar.start(test_case.name)

            if mode == validate.Mode.INPUT and not test_case.in_path.is_symlink() and not extra:
                t2 = self.matches_existing_test_case(test_case, localbar)
                if t2 is not None:
                    localbar.warn(
                        f"Duplicate test case: identical to {t2.name}. If this is intentional use symlinks/count/includes."
                    )
                    localbar.done()
                    return

            ok = test_case.validate_format(
                mode, bar=localbar, constraints=constraints_dict, warn_instead_of_error=extra
            )
            success &= ok
            localbar.done(ok)

        parallel.run_tasks(process_test_case, test_cases)

        bar.finalize(print_done=True)

        # Make sure all constraints are satisfied.
        if constraints_dict:
            for loc, value in sorted(constraints_dict.items()):
                loc = Path(loc).name
                name, has_low, has_high, vmin, vmax, low, high = value
                if not has_low:
                    success = False
                    warn(
                        f"BOUND NOT REACHED: `{name}` never equals lower bound {low}. Min value found: {vmin}"
                    )
                if not has_high:
                    success = False
                    warn(
                        f"BOUND NOT REACHED: `{name}` never equals upper bound {high}. Max value found: {vmax}"
                    )

        return success

    def validate_overrides(self) -> bool:
        overrides = self.overrides()
        if not overrides:
            return True

        extensions = [
            ".interaction",
            ".in.statement",
            ".in.download",
            ".ans.statement",
            ".ans.download",
        ]

        files = []
        for o in overrides:
            if isinstance(o.statement, Path):
                files.append(o.statement)
            else:
                files.extend(o.statement)
            files.extend(o.download)
        files = [f for f in files if any(f.name.endswith(ext) for ext in extensions)]

        # used to detect mixed up '<' and '>'
        def guess_prefix() -> Optional[bytes]:
            if not self.interactive:
                return None
            has_interaction = any(isinstance(o.statement, Path) for o in overrides)
            if not has_interaction:
                return None
            test_cases = self.test_cases()
            if not test_cases:
                return None
            test_case = test_cases[0]

            printed = interactive.interactor_prints_unprompted(self, test_case)
            if printed is None:
                return None
            return b"<" if printed else b">"

        prefix = guess_prefix() or b""
        if prefix:
            verbose(f"guessing that interactions must start with {prefix.decode()}")

        success = True
        data = self.path / "data"
        bar = ProgressBar("Overrides validation", items=[f.relative_to(data) for f in files])

        def process_file(file: Path) -> None:
            nonlocal success

            name = file.relative_to(data)
            localbar = bar.start(name)

            if file.name.endswith(".interaction"):
                if not validate.check_interaction(self, file, localbar, startswith=prefix):
                    success = False
                    return
            else:
                validate.sanity_check_override(self, file, localbar)

            localbar.done()

        parallel.run_tasks(process_file, files)
        bar.finalize(print_done=True)
        return True

    def determine_time_limit(self) -> bool:
        ts_pair = self.prepare_run()
        if not ts_pair:
            return False
        test_cases, submissions = ts_pair

        self.limits.time_limit = config.args.timeout or 60
        self.limits.time_limit_is_default = False
        self.limits.timeout = self.limits.time_limit + 1

        ok = True

        def run_all(
            skip_test_case: Callable[[Submission, TestCase], bool],
            select_duration: Callable[[Sequence[float]], float],
        ) -> tuple[str, str, float] | tuple[None, None, None]:
            nonlocal ok

            def skip_submission(s: Submission) -> bool:
                return all(skip_test_case(s, t) for t in test_cases)

            cur_submissions = [s for s in submissions if not skip_submission(s)]

            if len(cur_submissions) == 0:
                return None, None, None

            cur_ok, verdict_table = Problem.run_some(test_cases, cur_submissions, skip_test_case)
            if not cur_ok:
                ok = False

            def get_slowest(result: verdicts.Verdicts) -> tuple[str, float]:
                slowest_pair = result.slowest_test_case()
                assert slowest_pair is not None
                return slowest_pair

            durations = [get_slowest(result)[1] for result in verdict_table.results]
            selected = durations.index(select_duration(durations))
            test_case, duration = get_slowest(verdict_table.results[selected])
            return verdict_table.submissions[selected], test_case, duration

        # determine lower bound for time limit
        submission, slowest, duration = run_all(
            lambda s, t: all(not e.lower_time_limit for e in s.expectations.all_matches(t)),
            max,
        )
        if not ok:
            warn("Got unexpected verdicts")
        if submission is None:
            error("No submissions found to determine time limit")
            return False
        assert slowest is not None
        assert duration is not None

        raw_time_limit = duration * self.limits.ac_to_time_limit
        if config.args.local_time_multiplier is not None:
            raw_time_limit /= config.args.local_time_multiplier
        self.limits.raw_time_limit = self.limits.time_resolution * math.ceil(
            raw_time_limit / self.limits.time_resolution
        )
        self.limits.time_limit = self.limits.raw_time_limit
        if config.args.local_time_multiplier is not None:
            self.limits.time_limit *= config.args.local_time_multiplier
        safety_time_limit = self.limits.time_limit * self.limits.time_limit_to_tle
        self.limits.timeout = int(safety_time_limit * self.limits.time_limit_to_tle + 1)

        eprint()
        PrintBar("slowest").log(f"     {duration:.3f}s @ {slowest} ({submission})", color="")
        PrintBar("time limit").log(
            f"  {self.limits.time_limit:.1f}s >= {duration:.3f}s * {self.limits.ac_to_time_limit}",
            color="",
        )
        if config.args.local_time_multiplier is not None:
            warn(
                f"local_time_multiplier = {config.args.local_time_multiplier:.1f} => time_limit should be set as {self.limits.raw_time_limit}s"
            )
        PrintBar("safety limit").log(
            f"{safety_time_limit:.1f}s >= {self.limits.time_limit:.1f}s * {self.limits.time_limit_to_tle}",
            color="",
        )
        PrintBar("timeout").log(
            f"     {self.limits.timeout:.1f}s >= {self.limits.time_limit:.1f}s * {self.limits.time_limit_to_tle}²",
            color="",
        )
        eprint()

        if config.args.write:
            yaml_path = self.path / "problem.yaml"
            problem_yaml = read_yaml(yaml_path, empty=CommentedMap())
            if not isinstance(problem_yaml, CommentedMap):
                warn("could not parse problem.yaml")
            else:
                limits = ryaml_get_or_add(problem_yaml, "limits")
                limits["time_limit"] = self.limits.time_limit
                write_yaml(problem_yaml, self.path / "problem.yaml")

        # determine/check upper bound for time limit
        submission, fastest, duration = run_all(
            lambda s, t: all(not e.upper_time_limit for e in s.expectations.all_matches(t)),
            min,
        )
        if submission is not None:
            assert fastest is not None
            assert duration is not None
            eprint()
            PrintBar("fastest TLE").log(f" {duration:.3f}s @ {fastest} ({submission})", color="")
            if duration <= self.limits.time_limit:
                error("TLE submission runs within time limit")
            elif duration <= safety_time_limit:
                warn("TLE submission runs within safety margin")
            elif duration >= self.limits.timeout:
                log(f"No TLE submission finished within {self.limits.timeout}s")
            eprint()
        else:
            log("No TLE submissions found")

        if config.args.all:
            run_all(
                lambda s, t: any(
                    e.lower_time_limit or e.upper_time_limit for e in s.expectations.all_matches(t)
                ),
                max,
            )
        return ok
