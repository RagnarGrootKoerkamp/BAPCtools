import datetime
import math
import re
import shutil
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, Literal, Optional, overload, TYPE_CHECKING

from colorama import Fore, Style
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scanner import ScannerError

from bapctools import (
    check_testing_tool,
    config,
    latex,
    parallel,
    run,
    testcase,
    validate,
    validator_tests,
    verdicts,
    visualize,
)
from bapctools.util import (
    BAR_TYPE,
    combine_hashes_dict,
    drop_suffix,
    eprint,
    error,
    fatal,
    generate_problem_uuid,
    glob,
    hash_file_content,
    is_relative_to,
    is_uuid,
    log,
    math_eval,
    PrintBar,
    ProgressBar,
    read_yaml,
    resolve_path_argument,
    ryaml_get_or_add,
    verbose,
    warn,
    write_yaml,
    YamlParser,
)

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools.program import Program


class Person:
    def __init__(self, yaml_data: str | dict[object, object], parent_path: str):
        if isinstance(yaml_data, dict):
            parser = YamlParser("problem.yaml", yaml_data, parent_path)
            self.name: str = parser.extract("name", "")
            self.email: Optional[str] = parser.extract_optional("email", str)
            self.kattis: Optional[str] = parser.extract_optional("kattis", str)
            self.orcid: Optional[str] = parser.extract_optional("orcid", str)
            parser.check_unknown_keys()
        else:
            match = re.match("(.*)<(.*)>", yaml_data)
            self.name = (match[1] if match else yaml_data).strip()
            self.email = match[2].strip() if match else None
            self.kattis = self.orcid = None
        for token in [",", " and ", "&"]:
            if token in self.name:
                warn(
                    f"found suspicious token '{token.strip()}' in `{parent_path}.name`: {self.name}"
                )


class ProblemCredits:
    def __init__(self, parser: YamlParser):
        self.authors: list[Person] = []
        self.contributors: list[Person] = []
        self.testers: list[Person] = []
        self.translators: dict[str, list[Person]] = {}
        self.packagers: list[Person] = []
        self.acknowledgements: list[Person] = []

        parser.extract_deprecated("author", "credits.authors")
        if "credits" not in parser.yaml:
            return
        if isinstance(parser.yaml["credits"], str):
            self.authors = [Person(parser.extract("credits", ""), "credits")]
            return

        def extract_optional_persons(source: YamlParser, key: str) -> list[Person]:
            key_path = f"{source.parent_path}.{key}"
            if key in source.yaml:
                value = source.yaml.pop(key)
                if value is None:
                    return []
                if isinstance(value, (str, dict)):
                    return [Person(value, key_path)]
                if isinstance(value, list):
                    if not all(isinstance(v, (str, dict)) for v in value):
                        warn(
                            f"some values for key `{key_path}` in problem.yaml have invalid type. SKIPPED."
                        )
                        return []
                    if not value:
                        warn(f"value for `{key_path}` in problem.yaml should not be an empty list.")
                    return [Person(v, f"{key_path}[{i}]") for i, v in enumerate(value)]
                warn(f"incompatible value for key `{key_path}` in problem.yaml. SKIPPED.")
            return []

        credits = parser.extract_parser("credits")

        self.authors = extract_optional_persons(credits, "authors")
        self.contributors = extract_optional_persons(credits, "contributors")

        translators = credits.extract_parser("translators")
        self.translators = {}
        for lang in list(translators.yaml.keys()):
            if not isinstance(lang, str):
                warn(
                    f"invalid language `{lang}` for {translators.parent_str} in problem.yaml. SKIPPED."
                )
            else:
                self.translators[lang] = extract_optional_persons(translators, lang)

        self.testers = extract_optional_persons(credits, "testers")
        self.packagers = extract_optional_persons(credits, "packagers")
        self.acknowledgements = extract_optional_persons(credits, "acknowledgements")

        credits.check_unknown_keys()


class ProblemSource:
    def __init__(self, name: str, url: Optional[str] = None):
        self.name = name
        self.url = url

    def __repr__(self) -> str:
        return self.name + (f" ({self.url})" if self.url else "")


class ProblemSources(list[ProblemSource]):
    def __init__(self, parser: YamlParser):
        def parse_source(source: YamlParser) -> ProblemSource:
            name = source.extract_optional("name", str)
            url = source.extract_optional("url", str)
            if name is None:
                warn(f"problem.yaml: `name` is required in {source.parent_str}")
                name = ""
            source.check_unknown_keys()
            return ProblemSource(name, url)

        parser.extract_deprecated("source_url", "source.url")
        if "source" not in parser.yaml:
            return
        if isinstance(parser.yaml["source"], str):
            self.append(ProblemSource(parser.extract("source", "")))
            return
        if isinstance(parser.yaml["source"], dict):
            self.append(parse_source(parser.extract_parser("source")))
            return
        if isinstance(parser.yaml["source"], list):
            sources = parser.extract("source", list[object]())
            for i, source in enumerate(sources):
                if isinstance(source, str):
                    self.append(ProblemSource(source))
                elif isinstance(source, dict):
                    self.append(parse_source(YamlParser("problem.yaml", source, f"source[{i}]")))
                else:
                    warn(f"problem.yaml key `source[{i}]` does not have the correct type. SKIPPED.")
            return
        warn("problem.yaml key `source` does not have the correct type")


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

        self.time_limit_is_default: bool = "time_limit" not in parser.yaml
        self.raw_time_limit: float = parser.extract("time_limit", 1.0, "> 0")  # in seconds
        self.time_resolution: float = parser.extract("time_resolution", 1.0, "> 0")
        self.memory: int = parser.extract("memory", 2048, "> 0")  # in MiB
        self.output: int = parser.extract("output", 8, "> 0")  # in MiB
        self.code: int = parser.extract("code", 128, "> 0")  # in KiB
        self.compilation_time: int = parser.extract("compilation_time", 60, "> 0")  # in seconds
        self.compilation_memory: int = parser.extract("compilation_memory", 2048, "> 0")  # in MiB
        self.validation_time: int = parser.extract("validation_time", 60, "> 0")  # in seconds
        self.validation_memory: int = parser.extract("validation_memory", 2048, "> 0")  # in MiB
        self.validation_output: int = parser.extract("validation_output", 8, "> 0")  # in MiB
        if problem_settings.multi_pass:
            self.validation_passes: Optional[int] = parser.extract("validation_passes", 2, ">= 2")
        elif "validation_passes" in parser.yaml:
            parser.yaml.pop("validation_passes")
            warn("limit: validation_passes is only used for multi-pass problems. SKIPPED.")
            self.validation_passes = None

        # BAPCtools extensions:
        self.generator_time: int = parser.extract("generator_time", 60, "> 0")  # in seconds
        self.visualizer_time: int = parser.extract("visualizer_time", 60, "> 0")  # in seconds

        # warn for deprecated timelimit files
        if (problem.path / ".timelimit").is_file():
            warn("A .timelimit file is DEPRECATED. Use limits.time_limit instead.")
        if (problem.path / "domjudge-problem.ini").is_file():
            warn(
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
        yaml_data: dict[object, object],
        problem: "Problem",
    ):
        parser = YamlParser("problem.yaml", yaml_data)

        if isinstance(parser.yaml.get("name", None), str):
            parser.yaml["name"] = {"en": parser.yaml["name"]}

        # Known keys:
        # (defaults from https://icpc.io/problem-package-format/spec/2025-09.html#problem-metadata)
        self.problem_format_version: str = parser.extract("problem_format_version", "legacy-icpc")

        if self.problem_format_version.startswith("legacy"):
            fatal("legacy is no longer supported, try running 'bt upgrade'")
        elif self.problem_format_version != config.SPEC_VERSION:
            fatal(f"unrecognized problem_format_version: {self.problem_format_version}")

        parser.extract_deprecated("validation", "type")
        if "type" not in parser.yaml:
            mode = {"pass-fail"}
        elif isinstance(parser.yaml["type"], str):
            mode = set(parser.extract("type", "pass-fail").split())
        elif isinstance(yaml_data["type"], list):
            mode = set(parser.extract_optional_list("type", str))
            if not mode:
                mode = {"pass-fail"}
        else:
            fatal("problem.yaml: `type` must be a string or a sequence")
        unrecognized_type = mode - {"pass-fail", "interactive", "multi-pass"}
        if unrecognized_type:
            fatal(
                f"""problem.yaml: unrecognized value{
                    "" if len(unrecognized_type) == 1 else "s"
                } for `type`: {" ".join(sorted(unrecognized_type))}"""
            )
        self.interactive: bool = "interactive" in mode
        self.multi_pass: bool = "multi-pass" in mode
        self.custom_output: bool = (
            self.interactive
            or self.multi_pass
            or (problem.path / validate.OutputValidator.source_dir).is_dir()
        )

        names: dict[object, object] = parser.extract("name", {"en": ""})
        self.name: dict[str, str] = {}
        for lang, name in names.items():
            if not isinstance(lang, str):
                warn(f"invalid language `{lang}` for `name` in problem.yaml. SKIPPED.")
            elif not isinstance(name, str):
                warn(
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
            f"{validate.OutputValidator.args_key}' in 'test_group.yaml",
        )

        self.keywords: list[str] = parser.extract_optional_list("keywords", str, allow_empty=True)
        # Not implemented in BAPCtools. We always test all languages in languages.yaml.
        self.languages: list[str] = parser.extract_optional_list("languages", str)
        # Not implemented in BAPCtools
        self.allow_file_writing: bool = parser.extract("allow_file_writing", False)

        constants: dict[object, object] = parser.extract("constants", {})
        self.constants: dict[str, str] = {}
        for key, value in constants.items():
            if not isinstance(key, str) or not config.COMPILED_CONSTANT_NAME_REGEX.fullmatch(key):
                warn(f"invalid name `{key}` for `constants` in problem.yaml. SKIPPED.")
                continue

            variants = set()
            if not isinstance(value, dict):
                value = {"value": value}
            if "value" not in value:
                warn(f"missing `value` for key `constants.{key}` in problem.yaml. SKIPPED.")
                continue
            for sub, variant in value.items():
                if sub == "value" and isinstance(variant, (int, float)):
                    variant = str(variant)

                if not isinstance(sub, str):
                    warn(f"invalid key `constants.{key}.{sub}` in problem.yaml. SKIPPED.")
                elif not config.COMPILED_CONSTANT_NAME_REGEX.fullmatch(sub):
                    warn(f"invalid key `constants.{key}.{sub}` in problem.yaml. SKIPPED.")
                elif isinstance(variant, (int, float)):
                    warn(
                        f"invalid type {type(variant).__name__} for `constants.{key}.{sub}` in problem.yaml, use string. SKIPPED."
                    )
                elif not isinstance(variant, str):
                    warn(f"invalid type for `constants.{key}.{sub}` in problem.yaml. SKIPPED.")
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
                warn(f"found different variants for {key}: {', '.join(variant_numbers.values())}")

        # BAPCtools extensions:
        self.verified: Optional[str] = parser.extract_optional("verified", str)
        self.comment: Optional[str] = parser.extract_optional("comment", str)
        self.ans_is_output: bool = parser.extract(
            "ans_is_output", not self.interactive and not self.multi_pass
        )
        if (self.interactive or self.multi_pass) and self.ans_is_output:
            warn(f"ans_is_output: True makes no sense for {self.type_name()} problem. IGNORED.")
            self.ans_is_output = False

        parser.check_unknown_keys()

        # checks
        if not is_uuid(self.uuid):
            warn(f"invalid uuid: {self.uuid}")
        if self.license not in config.KNOWN_LICENSES:
            warn(f"invalid license: {self.license}")
            self.license = "unknown"
        if self.license == "public domain":
            if self.rights_owner is not None:
                warn(
                    f"problem cannot have license 'public domain' and have a rights owner: {self.rights_owner}"
                )
        elif self.license != "unknown":
            if self.rights_owner is None and not self.credits.authors and not self.source:
                warn(
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
    _SHORTNAME_REGEX_STRING: Final[str] = "[a-z0-9]{1,255}"
    _SHORTNAME_REGEX: Final[re.Pattern[str]] = re.compile(_SHORTNAME_REGEX_STRING)

    def __init__(self, path: Path, tmpdir: Path, label: Optional[str] = None):
        # The problem name/shortname, which is the name of the directory and used as a display name.
        self.name = path.name
        # The Path of the problem directory.
        self.path = path
        self.tmpdir: Path = tmpdir / self.name
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        # Read problem.yaml and domjudge-problem.ini into self.settings Namespace object.
        self._read_settings()

        # Some caches.
        self._testcases = dict[
            tuple[Optional[validate.Mode], bool, bool, bool], Sequence[testcase.Testcase]
        ]()
        self._submissions: Optional[Sequence[run.Submission] | Literal[False]] = None
        self._validators_cache = dict[  # The "bool" is for "check_constraints"
            tuple[type[validate.AnyValidator], bool], Sequence[validate.AnyValidator]
        ]()
        self._validators_warn_cache = set[tuple[type[validate.AnyValidator], bool]]()
        self._visualizer_cache = dict[
            type[visualize.AnyVisualizer], Optional[visualize.AnyVisualizer]
        ]()
        self._programs = dict[Path, "Program"]()
        self._program_callbacks = dict[Path, list[Callable[["Program"], None]]]()
        # Dictionary from path to parsed file contents.
        self._root_test_case_yaml: Optional[testcase.TestGroup] = None
        self._test_case_yamls = dict[Path, testcase.TestGroup]()
        self._test_group_lock = threading.Lock()

        # The label for the problem: A, B, A1, A2, X, ...
        self.label = label

        # TODO: transform this into nice warnings
        assert path.is_dir()
        if not Problem._SHORTNAME_REGEX.fullmatch(self.name):
            warn(
                f"Problem has a bad shortname: {self.name} does not match {self._SHORTNAME_REGEX_STRING}"
            )

        self.statement_languages = self._determine_statement_languages()

        for d in ["invalid_inputs", "invalid_answers", "invalid_outputs", "valid_outputs"]:
            if (self.path / "data" / d).is_dir():
                warn(f"Found directory: data/{d}, should be: data/{d[:-1]} (singular form).")

    def _determine_statement_languages(self) -> list[str]:
        """Determine the languages that are both mentioned in the problem.yaml under name
        and have a corresponding problem statement.

        If problem.yaml's name key is a string, convert into dict; assume `en` as default language.
        """
        yamllangs = set(self.settings.name)
        texlangs = set(
            path.suffixes[0][1:] for path in glob(self.path, str(latex.PdfType.PROBLEM.path("*")))
        )
        for lang in texlangs - yamllangs:
            error(
                f"{self.name}: Found {latex.PdfType.PROBLEM.path(lang).name}, but no corresponding name in problem.yaml."
            )
        for lang in yamllangs - texlangs:
            error(
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
                        error(rf"No \problemname found in {texpath.name}")
                        continue
                    case "":
                        continue
                    case r"\problemyamlname":
                        warn(
                            rf"Prefer using \problemname{{}} instead of \problemname{{\problemyamlname}} in {texpath.name}"
                        )
                        continue
                    case s if "\\" in s or "_" in s or "^" in s:
                        # texname contains markup, like "CO_2" or "\emph{Hello}":
                        # Assume authors know what they're doing
                        continue
                    case s if s != yamlname:
                        warn(
                            f"Problem titles in {texpath.name} ({texname})"
                            + f" and problem.yaml ({yamlname}) differ;"
                            + r" consider using \problemname{}."
                        )
        return sorted(texlangs & yamllangs)

    def _read_settings(self) -> None:
        # parse problem.yaml
        yaml_path = self.path / "problem.yaml"
        try:
            yaml_data = read_yaml(yaml_path) or {}
        except ScannerError:
            fatal(f"Make sure {self.name}/problem.yaml does not contain any more {{% ... %}}.")

        if not isinstance(yaml_data, dict):
            fatal(f"{self.name}/problem.yaml is illformed.")

        if "uuid" not in yaml_data:
            uuid = generate_problem_uuid()
            yaml_data["uuid"] = uuid
            raw = yaml_path.read_text().rstrip()
            raw += f"\n# uuid added by BAPCtools\nuuid: '{uuid}'\n"
            yaml_path.write_text(raw)
            log(f"Added new UUID to {self.name}/problem.yaml")

        self.settings = ProblemSettings(yaml_data, self)

        # Aliasing fields makes life easier for us 😛
        self.limits: ProblemLimits = self.settings.limits
        self.interactive: bool = self.settings.interactive
        self.multi_pass: bool = self.settings.multi_pass
        self.custom_output: bool = self.settings.custom_output

    def get_test_case_yaml(
        p,
        path: Path,
        bar: BAR_TYPE,
    ) -> testcase.TestGroup:
        """
        Find the test_group.yaml for the given path.
        If necessary, walk up from `path` looking for the first test_group.yaml file that applies.

        Side effects: parses and caches the file.

        Arguments
        ---------
        path: absolute path (a <test_case>.yaml file or a test group directory)

        Returns:
        --------
        A testcase.TestGroup object
        """
        assert path.is_relative_to(p.path / "data"), f"{path} is not in data"

        paths = []
        for f in [path, *path.parents]:
            # Do not go above the data directory.
            if f == p.path:
                break
            paths.append(f)

        # create a root testcase.TestGroup object
        if p._root_test_case_yaml is None:
            with p._test_group_lock:
                if p._root_test_case_yaml is None:
                    p._root_test_case_yaml = testcase.TestGroup(p, None, {}, None, bar)

        test_group_yaml = p._root_test_case_yaml
        for f in reversed(paths):
            if f.is_dir():
                f = f / "test_group.yaml"
            if not f.is_file():
                continue
            if f not in p._test_case_yamls:
                with p._test_group_lock:
                    # handle race conditions
                    if f not in p._test_case_yamls:
                        p._test_case_yamls[f] = testcase.TestGroup.parse_yaml(
                            p, f, test_group_yaml, bar
                        )
            assert f in p._test_case_yamls
            test_group_yaml = p._test_case_yamls[f]
        return test_group_yaml

    # Because Problem.testcases() may be called multiple times (e.g. validating multiple modes, or with `bt all`),
    # this cache makes sure that some warnings (like malformed test case names) only appear once.
    _warned_for_test_case = set[str]()

    def _warn_once(p, test_name: str, msg: str) -> None:
        if test_name not in p._warned_for_test_case:
            p._warned_for_test_case.add(test_name)
            warn(msg)

    def testcases(
        p,
        *,
        mode: Optional[validate.Mode] = None,
        needans: bool = True,
        only_samples: bool = False,
        testing_tool_test: bool = False,
    ) -> Sequence[testcase.Testcase]:
        only_samples = config.args.samples or only_samples

        key = (mode, needans, only_samples, testing_tool_test)
        if key in p._testcases is not None:
            return p._testcases[key]

        in_paths = None
        if config.args.testcases:
            assert not only_samples
            # Deduplicate testcases with both .in and .ans.
            in_paths = []
            for path in config.args.testcases:
                res_path = resolve_path_argument(p, path, "data", suffixes=[".in"])
                if res_path:
                    # When running from contest level, the testcase must be inside the problem.
                    if config.level != "problemset" or is_relative_to(p.path, res_path):
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
                in_paths += glob(p.path, f"data/{prefix}/**/*.in")
        elif testing_tool_test:
            in_paths = list(glob(p.path, "data/testing_tool_test/**/*.in"))
        else:
            in_paths = list(glob(p.path, "data/sample/**/*.in"))
            if not only_samples:
                in_paths += list(glob(p.path, "data/secret/**/*.in"))

        testcases = []
        for f in in_paths:
            t = testcase.Testcase(p, f)
            if not config.COMPILED_FILE_NAME_REGEX.fullmatch(f.name):
                p._warn_once(t.name, f"Test case name {t.name} is not valid. Skipping.")
                continue
            if f.with_suffix("").name == "test_group":
                p._warn_once(
                    t.name,
                    "Test case must not be named 'test_group', this clashes with the group-level 'test_group.yaml'. Skipping.",
                )
                continue
            if (
                (p.interactive or p.multi_pass)
                and mode in [validate.Mode.INVALID, validate.Mode.VALID_OUTPUT]
                and t.root in ["invalid_output", "valid_output"]
            ):
                p._warn_once(
                    t.name,
                    f"Found file {f} for {mode} validation in {p.settings.type_name()} problem. Skipping.",
                )
                continue
            if needans and not t.ans_path.is_file():
                if t.root != "invalid_input":
                    p._warn_once(t.name, f"Found input file {f} without a .ans file. Skipping.")
                    continue
            if t.root in ["valid_output", "invalid_output"]:
                assert t.out_path is not None
                if not t.out_path.is_file():
                    p._warn_once(t.name, f"Found input file {f} without a .out file. Skipping.")
                    continue
            if mode == validate.Mode.VALID_OUTPUT:
                if t.out_path is None:
                    continue
                if not t.out_path.is_file():
                    warn(f"Found input file {f} without a .out file. Skipping.")
                    continue
            testcases.append(t)
        testcases.sort(key=lambda t: t.name)

        if len(testcases) == 0 and not testing_tool_test:
            ans = (
                " with answer"
                if needans and mode not in [validate.Mode.INVALID, validate.Mode.VALID_OUTPUT]
                else ""
            )
            val = f" for {mode} validation" if mode is not None else ""
            # TODO perhaps move this log to the use site?
            (log if mode in [validate.Mode.INVALID, validate.Mode.VALID_OUTPUT] else warn)(
                f"Didn't find any testcases{ans}{val} in problem {p.name}. Skipping."
            )

        p._testcases[key] = tuple(testcases)
        return p._testcases[key]

    def _samples(
        p, in_extensions: list[str], ans_extensions: list[str], return_interaction_file: bool
    ) -> list[Path | tuple[Path, Path]]:
        """
        Find the samples of the problem

        Arguments
        ---------
        in_extensions: possible extensions for an in file sorted by priority
        ans_extensions: possible extensions for an ans file sorted by priority
        return_interaction_file: If True allows to represent testcases by an .interaction file

        Returns:
        --------
        A list of testcases represented either by their .interaction file or an in and ans file
        """

        base_names: set[Path] = set()
        for ext in [".in", ".in.statement", ".interaction"]:
            files = list(p.path.glob(f"data/sample/**/*{ext}"))
            base_names.update([drop_suffix(f, [ext]) for f in files if f.is_file()])
        testcases: list[Path | tuple[Path, Path]] = []
        has_raw = False
        for name in base_names:
            in_found = [ext for ext in in_extensions if name.with_suffix(ext).is_file()]
            ans_found = [ext for ext in ans_extensions if name.with_suffix(ext).is_file()]
            has_statement = ".in.statement" in in_found or ".ans.statement" in ans_found

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
            if has_statement and ".out" in ans_found:
                # we prefer .statement files
                warn(f"Found {name}.out (but also .statement). IGNORED.")
                ans_found.remove(".out")

            # .interaction files get highest priority
            if return_interaction_file and name.with_suffix(".interaction").is_file():
                if not p.interactive and not p.multi_pass:
                    warn(f"Found {name}.interaction for non-interactive/non-multi-pass. IGNORED.")
                else:
                    if has_statement:
                        warn(
                            f"Mixed .interaction and .statement file for {name}. (using .interaction)."
                        )
                    if ".out" in ans_found:
                        warn(f"Mixed .interaction and .out file for {name}. (using .interaction).")
                    testcases.append(name.with_suffix(".interaction"))
                    continue

            if not in_found or not ans_found:
                warn(
                    f"Could not find valid .in/.ans combination for test case {name}. SKIPPED."
                    + "\n\tNumbering for statement and download could be inconsistent!"
                )
                continue

            if (
                not name.with_suffix(".interaction").is_file()
                and ans_found[0] == ".ans"
                and name.with_suffix(in_found[0]).stat().st_size > 0
                and name.with_suffix(ans_found[0]).stat().st_size > 0
            ):
                has_raw = True

            # fallback is pair of files
            testcases.append((name.with_suffix(in_found[0]), name.with_suffix(ans_found[0])))

        if has_raw and not p.settings.ans_is_output:
            warn(
                "It is advised to overwrite .ans for samples if it does not represent a valid output."
                + "\n\tUse .ans.statement or .out for this."
            )

        testcases.sort()
        return testcases

    # Returns a list of:
    # - (Path, Path): with the first being one of [.in.statement, .in] and the second one of [.ans.statement, .out, .ans]
    # -  Path       :  .interaction file
    def statement_samples(p) -> list[Path | tuple[Path, Path]]:
        in_extensions = [
            ".in.statement",
            ".in",
        ]
        ans_extensions = [
            ".ans.statement",
            ".out",
            ".ans",
        ]
        return p._samples(in_extensions, ans_extensions, True)

    # Returns a list of:
    # - (Path, Path): with the first being one of [.in.download, .in.statement, .in] and the second one of [.ans.download, .ans.statement, .out, .ans]
    def download_samples(p) -> list[tuple[Path, Path]]:
        in_extensions = [
            ".in.download",
            ".in.statement",
            ".in",
        ]
        ans_extensions = [
            ".ans.download",
            ".ans.statement",
            ".out",
            ".ans",
        ]
        testcases = p._samples(in_extensions, ans_extensions, False)
        return [t for t in testcases if isinstance(t, tuple)]

    # Returns the list of submissions passed as command-line arguments, or the list of accepted submissions by default.
    def selected_or_accepted_submissions(problem) -> Sequence[run.Submission]:
        submissions = problem.submissions()
        if not submissions:
            return tuple()
        if config.args.submissions:
            return submissions
        else:
            return tuple(
                s for s in submissions if s.expected_verdicts == [verdicts.Verdict.ACCEPTED]
            )

    def submissions(problem) -> Sequence[run.Submission] | Literal[False]:
        if problem._submissions is not None:
            if problem._submissions is False:
                return False
            else:
                return problem._submissions

        paths = []
        if config.args.submissions:

            def add(s: Path) -> None:
                if s in paths:
                    warn(f"Ignoring duplicate submission: {s}")
                    return
                paths.append(s)

            for submission in config.args.submissions:
                s = resolve_path_argument(problem, submission, "submissions")
                if s:
                    if s == problem.path / "submissions":
                        paths += glob(s, "*/*")
                    elif s.parent == problem.path / "submissions":
                        for s in glob(s, "*"):
                            add(s)
                    else:
                        # If running from a contest, the submission must be inside a problem.
                        if config.level == "problem" or is_relative_to(problem.path, s):
                            add(s)
        else:
            for s in glob(problem.path / "submissions", "*/*"):
                if (
                    s.parent.name == "time_limit_exceeded"
                    and config.RUNNING_TEST
                    and not config.TEST_TLE_SUBMISSIONS
                ):
                    continue

                paths.append(s)

        if len(paths) == 0:
            error("No submissions found!")
            problem._submissions = False
            return False

        programs = [run.Submission(problem, path) for path in paths]

        # - first all submission with just one verdict (grouped by that verdict and sorted by the path)
        # - then by subdir
        # - then by list of verdicts
        # - then by name
        def submissions_key(
            x: run.Submission,
        ) -> tuple[int, str, Sequence[verdicts.Verdict], str, str]:
            group = "" if len(x.expected_verdicts) == 1 else x.subdir
            return (len(x.expected_verdicts), group, x.expected_verdicts, x.subdir, x.name)

        programs.sort(key=submissions_key)

        bar = ProgressBar("Build submissions", items=programs)

        def build_program(p: run.Submission) -> None:
            localbar = bar.start(p)
            p.build(localbar)
            localbar.done()

        parallel.run_tasks(build_program, programs)

        bar.finalize(print_done=False)

        # Filter out broken submissions.
        problem._submissions = tuple(p for p in programs if p.ok)

        if len(problem._submissions) == 0:
            problem._submissions = False
            return False

        assert isinstance(problem._submissions, tuple)
        return problem._submissions

    @overload
    def visualizer(
        problem, cls: type[visualize.InputVisualizer]
    ) -> Optional[visualize.InputVisualizer]: ...
    @overload
    def visualizer(
        problem, cls: type[visualize.OutputVisualizer]
    ) -> Optional[visualize.OutputVisualizer]: ...
    def visualizer(
        problem, cls: type[visualize.AnyVisualizer]
    ) -> Optional[visualize.AnyVisualizer]:
        path = problem.path / cls.source_dir
        if not path.is_dir():
            return None
        if cls not in problem._visualizer_cache:
            visualizer = cls(problem, path)
            bar = ProgressBar(f"Building {cls.visualizer_type} visualizer", items=[visualizer])
            localbar = bar.start(visualizer)
            visualizer.build(localbar)
            localbar.done()
            bar.finalize(print_done=False)
            problem._visualizer_cache[cls] = visualizer if visualizer.ok else None
        return problem._visualizer_cache[cls]

    def validators(
        problem,
        cls: type[validate.AnyValidator],
        check_constraints: bool = False,
        strict: bool = False,
        print_warn: bool = True,
    ) -> Sequence[validate.AnyValidator]:
        """
        Gets the validators of the given class.
        If strict is true we only return the validators as the icpc specification indicates.
        If strict is false we may return additional validators (right now we return OutputValidators as AnswerValidators).

        If needed, builds them.

        problem._validators_cache caches previous calls to avoid rebuilding

        Returns:
            singleton list(OutputValidator) if cls is OutputValidator
            list(Validator) otherwise, maybe empty
        """
        validators = problem._validators(cls, check_constraints)
        if not strict and cls == validate.AnswerValidator and problem.settings.ans_is_output:
            validators = (
                *validators,
                *problem._validators(validate.OutputValidator, check_constraints),
            )

        # Check that the proper number of validators is present
        # do this after handling the strict flag but do not warn every time
        if print_warn:
            key = (cls, check_constraints)
            if key not in problem._validators_warn_cache:
                constraints_msg = " for constraints checking" if check_constraints else ""
                problem._validators_warn_cache.add(key)
                if cls == validate.InputValidator and not validators:
                    warn(f"No input validators{constraints_msg} found.")
                if cls == validate.AnswerValidator and not validators and not problem.interactive:
                    # for interactive problems, the .ans file should be empty
                    warn(f"No answer validators{constraints_msg} found.")

        build_ok = all(v.ok for v in validators)

        # All validators must build.
        # TODO Really? Why not at least return those that built?
        return validators if build_ok else tuple()

    def _validators(
        problem, cls: type[validate.AnyValidator], check_constraints: bool = False
    ) -> Sequence[validate.AnyValidator]:
        key = (cls, check_constraints)
        if key in problem._validators_cache:
            return problem._validators_cache[key]

        if cls == validate.OutputValidator:
            if problem.custom_output:
                paths = [problem.path / validate.OutputValidator.source_dir]
            else:
                paths = [config.RESOURCES_ROOT / "support" / "default_output_validator.cpp"]
        else:
            paths = list(glob(problem.path / cls.source_dir, "*"))

        # TODO: Instead of checking file contents, maybe specify this in generators.yaml?
        def has_constraints_checking(f: Path) -> bool:
            if not f.is_file():
                return False
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
                problem,
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

        problem._validators_cache[key] = validators
        return validators

    # get all testcases and submissions and prepare the output validator and visualizer
    def prepare_run(
        problem,
    ) -> Literal[False] | tuple[Sequence[testcase.Testcase], Sequence[run.Submission]]:
        testcases = problem.testcases()
        if not testcases:
            return False

        # Pre build the output validator to prevent nested ProgressBars.
        if not problem.validators(validate.OutputValidator):
            return False

        # Pre build the output visualizer to prevent nested ProgressBars.
        if not config.args.no_visualizer:
            problem.visualizer(visualize.OutputVisualizer)

        submissions = problem.submissions()
        if not submissions:
            return False

        return testcases, submissions

    @staticmethod
    def run_some(
        testcases: Sequence[testcase.Testcase], submissions: Sequence[run.Submission]
    ) -> tuple[bool, verdicts.VerdictTable]:
        max_submission_len = max([len(x.name) for x in submissions])

        ok = True
        verdict_table = verdicts.VerdictTable(submissions, testcases)
        # When true, the ProgressBar will print a newline before the first error log.
        needs_leading_newline = False if config.args.verbose else True
        for submission in submissions:
            submission_ok, printed_newline = submission.run_testcases(
                max_submission_len,
                verdict_table,
                testcases,
                needs_leading_newline=needs_leading_newline,
            )
            needs_leading_newline = not printed_newline
            ok &= submission_ok
        return ok, verdict_table

    # called by bt run
    def run_submissions(problem) -> bool:
        ts_pair = problem.prepare_run()
        if not ts_pair:
            return False
        testcases, submissions = ts_pair

        msg = (
            "localy adjusted "
            if config.args.local_time_multiplier is not None and config.args.time_limit is None
            else ""
        )
        PrintBar("Run").log(f"using {msg}timelimit: {problem.limits.time_limit:.1f}s\n", color="")

        ok, verdict_table = Problem.run_some(testcases, submissions)

        if (
            len(testcases) * len(submissions) > 1
            and not config.args.verbose
            and not config.args.no_visualizer
            and problem.visualizer(visualize.OutputVisualizer)
        ):
            log("use -v with --visualize to see the paths to the generated images")

        if config.args.table:
            Problem._print_table(verdict_table.results, testcases)
        elif config.args.overview and not config.args.tree:
            verdict_table.print(force=True, new_lines=1)

        return ok

    # Takes a list of submissions and runs them against the chosen testcases.
    # Instead of validating the output, this function just prints all output to the
    # terminal.
    # Note: The CLI only accepts one submission.
    def test_submissions(problem) -> bool:
        submissions = problem.submissions()
        if submissions is False:
            return False

        for submission in submissions:
            if config.args.interactive:
                submission.test_interactive()
            else:
                submission.test()
        return True

    @staticmethod
    def _print_table(
        verdict_table: Sequence[verdicts.Verdicts], testcases: Sequence[testcase.Testcase]
    ) -> None:
        # Begin by aggregating bitstrings for all testcases, and find bitstrings occurring often (>=config.TABLE_THRESHOLD).
        def single_verdict(row: verdicts.Verdicts, testcase: testcase.Testcase) -> str:
            assert row[testcase.name] is not None
            if row[testcase.name] is not False:
                return verdicts.to_char(row[testcase.name])
            else:
                return f"{Style.DIM}-{Style.RESET_ALL}"

        def make_verdict(tc: testcase.Testcase) -> str:
            return "".join(map(lambda row: single_verdict(row, tc), verdict_table))

        resultant_count, resultant_id = dict[str, int](), dict[str, int]()
        special_id = 0
        for case in testcases:
            resultant = make_verdict(case)
            if resultant not in resultant_count:
                resultant_count[resultant] = 0
            resultant_count[resultant] += 1
            if resultant_count[resultant] == config.TABLE_THRESHOLD:
                special_id += 1
                resultant_id[resultant] = special_id

        scores = dict[str, float]()
        for t in testcases:
            scores[t.name] = 0
        for dct in verdict_table:
            failures = 0
            for t in testcases:
                if dct[t.name] != verdicts.Verdict.ACCEPTED:
                    failures += 1
            for t in testcases:
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
        eprint(f"{fail}: submission fails testcase")
        eprint(f"{verdicts.to_char(verdicts.Verdict.ACCEPTED)}: submission passes testcase\n")

        name_col_width = min(50, max([len(testcase.name) for testcase in testcases]))

        for case in testcases:
            # Skip all AC testcases
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
    def check_testing_tool(problem) -> bool:
        testcases = problem.testcases(needans=False, testing_tool_test=True)
        testinputs = [
            check_testing_tool.TestInput(problem, t.in_path, t.short_path) for t in testcases
        ]
        if not config.args.testcases:
            sampleinputs = []
            for in_path, _ in problem.download_samples():
                sample = check_testing_tool.TestInput(
                    problem, in_path, in_path.relative_to(problem.path / "data")
                )
                if sample not in testinputs:
                    sampleinputs.append(sample)
            testinputs = sampleinputs + testinputs
        if not testinputs:
            warn(
                f"Didn't find any testcases to run the testing tool in problem {problem.name}. Skipping."
            )
            return False
        submissions = problem.selected_or_accepted_submissions()
        if not submissions:
            return False
        return check_testing_tool.run(problem, testinputs, submissions)

    def reset_testcase_hashes(self) -> None:
        self._testcase_hashes: dict[str, testcase.Testcase] = {}

    # Returns None for new testcases or the Testcase object it equals.
    def matches_existing_testcase(self, t: testcase.Testcase) -> Optional[testcase.Testcase]:
        hashes = {}
        relevant_files = {
            "invalid_input": ["in"],
            "invalid_answer": [".in", ".ans"],
            "invalid_output": [".in", ".ans", ".out"],
            "valid_output": [".in", ".ans", ".out"],
        }
        relevant_files_default = [".in"] if self.settings.ans_is_output else [".in", ".ans"]
        extensions = relevant_files.get(t.root, relevant_files_default)

        for ext in extensions:
            if t.with_suffix(ext).is_file():
                hashes[ext] = hash_file_content(t.with_suffix(ext))

        h = combine_hashes_dict(hashes)
        if h in self._testcase_hashes:
            return self._testcase_hashes[h]
        self._testcase_hashes[h] = t
        return None

    def validate_data(
        problem,
        mode: validate.Mode,
        constraints: validate.ConstraintsDict | Literal[True] | None = None,
    ) -> bool:
        """Validate aspects of the test data files.

        Arguments:
            mode: validate.Mode.INPUT | validate.Mode.ANSWER | validate.Mode.INVALID | validate.Mode.VALID_OUTPUT
            constraints: True | dict | None. True means "do check constraints but discard the result."
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

        testcases = problem.testcases(mode=mode)
        return problem._validate_data(mode, constraints, action, testcases)

    def validate_invalid_extra_data(p) -> bool:
        assert config.args.generic is not None
        base_path = p.tmpdir / "invalid_data"
        # pick at most first 3 samples (assuming they are valid and have .ans)
        # also add a dummy entry to always run generators that don't read or copy anything from a valid testcase
        samples = sorted(glob(p.path, "data/sample/**/*.in"))[:3] + [None]

        # validator, dir, read, write, copy
        validators: list[tuple[type[validate.AnyValidator], str, str, str, list[str]]] = [
            (validate.InputValidator, "invalid_input", ".in", ".in", []),
            (validate.AnswerValidator, "invalid_answer", ".ans", ".ans", [".in"]),
            (
                validate.OutputValidator,
                "invalid_output",
                ".ans" if p.settings.ans_is_output else ".out",
                ".out",
                [".in", ".ans"],
            ),
        ]

        testcases: list[testcase.Testcase] = []
        for i, sample in enumerate(samples):
            used_sample = False
            for cls, directory, read, write, copy in validators:
                if directory not in config.args.generic:
                    continue
                if p.interactive and cls != validate.InputValidator:
                    continue
                if p.multi_pass and cls == validate.OutputValidator:
                    continue
                if not p.validators(cls, strict=True, print_warn=False):
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
                    testcases.append(testcase.Testcase(p, full_path, short_path=short_path))
            if used_sample:
                assert sample is not None
                sample_name = sample.relative_to(p.path / "data").with_suffix("")
                log(f"Generated invalid testcases based on: {sample_name}")
        if testcases:
            verbose(f"writing generated invalid testcases to: {base_path}")

        return p._validate_data(
            validate.Mode.INVALID, None, "Generic Invalidation", testcases, True
        )

    def validate_valid_extra_data(p) -> bool:
        assert config.args.generic is not None
        if "valid_output" not in config.args.generic:
            return True
        if p.interactive or p.multi_pass:
            return True
        if not p.validators(validate.OutputValidator, strict=True, print_warn=False):
            return True

        args = p.get_test_case_yaml(
            p.path / "data" / "valid_output",
            PrintBar("Generic Output Validation"),
        ).output_validator_args
        is_space_sensitive = "space_change_sensitive" in args
        is_case_sensitive = "case_sensitive" in args

        base_path = p.tmpdir / "valid_data"
        # pick at most first 3 samples (assuming they are valid and have .ans)
        samples = sorted(glob(p.path, "data/sample/**/*.in"))[:3]
        samples = [p for p in samples if p.with_suffix(".ans").exists()]

        testcases: list[testcase.Testcase] = []
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
                testcases.append(testcase.Testcase(p, full_path, short_path=short_path))
            if used_sample:
                assert sample is not None
                sample_name = sample.relative_to(p.path / "data").with_suffix("")
                log(f"Generated valid testcases based on: {sample_name}")
        if testcases:
            verbose(f"writing generated valid testcases to: {base_path}")

        return p._validate_data(
            validate.Mode.VALID_OUTPUT, None, "Generic Output Validation", testcases, True
        )

    def _validate_data(
        problem,
        mode: validate.Mode,
        constraints: validate.ConstraintsDict | Literal[True] | None,
        action: str,
        testcases: Sequence[testcase.Testcase],
        extra: bool = False,
    ) -> bool:
        # If there are no testcases, validation succeeds
        if not testcases:
            return True

        constraints_dict = {} if constraints is True else constraints
        check_constraints = constraints_dict is not None

        # Pre-build the relevant Validators so as to avoid clash with ProgressBar bar below
        # Also, pick the relevant testcases
        match mode:
            case validate.Mode.INPUT:
                problem.validators(validate.InputValidator, check_constraints=check_constraints)
            case validate.Mode.ANSWER:
                problem.validators(validate.AnswerValidator, check_constraints=check_constraints)
            case validate.Mode.INVALID:
                problem.validators(validate.InputValidator)
                problem.validators(validate.AnswerValidator)
                problem.validators(validate.OutputValidator)
            case validate.Mode.VALID_OUTPUT:
                problem.validators(validate.InputValidator)
                problem.validators(validate.AnswerValidator)
                problem.validators(validate.OutputValidator)
            case _:
                raise ValueError(mode)

        success = True

        problem.reset_testcase_hashes()

        # validate the testcases
        bar = ProgressBar(action, items=[t.name for t in testcases])

        def process_testcase(testcase: testcase.Testcase) -> None:
            nonlocal success

            localbar = bar.start(testcase.name)

            if mode == validate.Mode.INPUT and not testcase.in_path.is_symlink() and not extra:
                t2 = problem.matches_existing_testcase(testcase)
                if t2 is not None:
                    localbar.warn(
                        f"Duplicate testcase: identical to {t2.name}. If this is intentional use symlinks/count/includes."
                    )
                    localbar.done()
                    return

            ok = testcase.validate_format(
                mode, bar=localbar, constraints=constraints_dict, warn_instead_of_error=extra
            )
            success &= ok
            localbar.done(ok)

        parallel.run_tasks(process_testcase, testcases)

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

    def determine_time_limit(problem) -> bool:
        ts_pair = problem.prepare_run()
        if not ts_pair:
            return False
        testcases, submissions = ts_pair

        ok = True
        problem.limits.time_limit = config.args.timeout or 60
        problem.limits.time_limit_is_default = False
        problem.limits.timeout = problem.limits.time_limit + 1

        def run_all(
            select_verdict: Callable[[Sequence[verdicts.Verdict]], bool],
            select: Callable[[Sequence[float]], float],
        ) -> tuple[str, str, float] | tuple[None, None, None]:
            nonlocal ok

            cur_submissions = [s for s in submissions if select_verdict(s.expected_verdicts)]

            if len(cur_submissions) == 0:
                return None, None, None

            cur_ok, verdict_table = Problem.run_some(testcases, cur_submissions)
            if not cur_ok:
                ok = False
                return None, None, None

            def get_slowest(result: verdicts.Verdicts) -> tuple[str, float]:
                slowest_pair = result.slowest_test_case()
                assert slowest_pair is not None
                return slowest_pair

            durations = [get_slowest(result)[1] for result in verdict_table.results]
            selected = durations.index(select(durations))
            testcase, duration = get_slowest(verdict_table.results[selected])
            return verdict_table.submissions[selected], testcase, duration

        submission, testcase, duration = run_all(lambda vs: vs == [verdicts.Verdict.ACCEPTED], max)
        if not ok:
            error("AC submissions failed")
            return False
        if submission is None:
            error("No AC submissions found")
            return False
        assert testcase is not None
        assert duration is not None

        raw_time_limit = duration * problem.limits.ac_to_time_limit
        if config.args.local_time_multiplier is not None:
            raw_time_limit /= config.args.local_time_multiplier
        problem.limits.raw_time_limit = problem.limits.time_resolution * math.ceil(
            raw_time_limit / problem.limits.time_resolution
        )
        problem.limits.time_limit = problem.limits.raw_time_limit
        if config.args.local_time_multiplier is not None:
            problem.limits.time_limit *= config.args.local_time_multiplier
        safety_time_limit = problem.limits.time_limit * problem.limits.time_limit_to_tle
        problem.limits.timeout = int(safety_time_limit * problem.limits.time_limit_to_tle + 1)

        eprint()
        PrintBar("slowest AC").log(f"  {duration:.3f}s @ {testcase} ({submission})", color="")
        PrintBar("time limit").log(
            f"  {problem.limits.time_limit:.1f}s >= {duration:.3f}s * {problem.limits.ac_to_time_limit}",
            color="",
        )
        if config.args.local_time_multiplier is not None:
            warn(
                f"local_time_multiplier = {config.args.local_time_multiplier:.1f} => time_limit should be set as {problem.limits.raw_time_limit}s"
            )
        PrintBar("safety limit").log(
            f"{safety_time_limit:.1f}s >= {problem.limits.time_limit:.1f}s * {problem.limits.time_limit_to_tle}",
            color="",
        )
        PrintBar("timeout").log(
            f"     {problem.limits.timeout:.1f}s >= {problem.limits.time_limit:.1f}s * {problem.limits.time_limit_to_tle}²",
            color="",
        )
        eprint()

        if config.args.write:
            yaml_path = problem.path / "problem.yaml"
            problem_yaml = read_yaml(yaml_path)
            if problem_yaml is None:
                problem_yaml = CommentedMap()
            if not isinstance(problem_yaml, CommentedMap):
                warn("could not parse problem.yaml")
            else:
                limits = ryaml_get_or_add(problem_yaml, "limits")
                limits["time_limit"] = problem.limits.time_limit
                write_yaml(problem_yaml, problem.path / "problem.yaml")

        submission, testcase, duration = run_all(
            lambda vs: vs == [verdicts.Verdict.TIME_LIMIT_EXCEEDED], min
        )
        if submission is not None:
            assert testcase is not None
            assert duration is not None
            eprint()
            PrintBar("fastest TLE").log(f" {duration:.3f}s @ {testcase} ({submission})", color="")
            if duration <= problem.limits.time_limit:
                error("TLE submission runs within time limit")
            elif duration <= safety_time_limit:
                warn("TLE submission runs within safety margin")
            elif duration >= problem.limits.timeout:
                log(f"No TLE submission finished within {problem.limits.timeout}s")
            eprint()
        else:
            log("No TLE submissions found")

        if config.args.all:
            submission, testcase, duration = run_all(
                lambda vs: vs != [verdicts.Verdict.ACCEPTED]
                and vs != [verdicts.Verdict.TIME_LIMIT_EXCEEDED],
                max,
            )
            if submission is not None:
                assert testcase is not None
                assert duration is not None
                if duration > problem.limits.time_limit:
                    warn("Non TLE submission timed out")
                else:
                    log("All non TLE submission finished within time limit")
        return ok
