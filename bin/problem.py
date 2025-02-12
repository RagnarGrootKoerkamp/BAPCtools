import re
import shlex
import sys
import threading

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from program import Program

import config
import latex
import math
import parallel
import run
import testcase
import validate
import validator_tests
import verdicts
from util import *
from colorama import Fore, Style


# Parse validation mode (only for legacy problem format version)
def parse_legacy_validation(mode: str) -> set[str]:
    if mode == "default":
        return {mode}
    else:
        ok = True
        parsed = set()
        for part in mode.split():
            if part in ["custom", "interactive", "multi-pass"] and part not in parsed:
                parsed.add(part)
            else:
                ok = False
        if "custom" not in parsed or not ok:
            fatal(f"Unrecognised validation mode {mode}.")
        return parsed


class ProblemCredits:
    def __init__(
        self,
        yaml_data: dict[str, Any],
        problem_settings: "ProblemSettings",
    ):
        self.authors: list[str] = []
        self.contributors: list[str] = []
        self.testers: list[str] = []
        self.translators: dict[str, list[str]] = {}
        self.packagers: list[str] = []
        self.acknowledgements: list[str] = []

        # If problem.yaml uses the legacy version, do not support the new `credits` key.
        # If problem.yaml uses 2023-07-draft, prefer `credit`, but also support `author` and warn for it.
        legacy_author = parse_optional_setting(yaml_data, "author", str)
        if problem_settings.is_legacy():
            if legacy_author:
                if "," in legacy_author:
                    self.authors = [author.strip() for author in legacy_author.split(",")]
                elif "and" in legacy_author:
                    self.authors = [author.strip() for author in legacy_author.split("and")]
                else:
                    self.authors = [legacy_author]
        else:
            if legacy_author is not None:
                warn("problem.yaml: author is removed in 2023-07-draft, please use credits.authors")
            if "credits" not in yaml_data:
                return
            if isinstance(yaml_data["credits"], str):
                self.authors = [parse_setting(yaml_data, "credits", "")]
                return

            credits = parse_setting(yaml_data, "credits", dict[str, Any]())
            self.authors = parse_optional_list_setting(credits, "authors", str)
            self.contributors = parse_optional_list_setting(credits, "contributors", str)
            self.translators = parse_setting(credits, "translators", {})
            for lang in self.translators:
                self.translators[lang] = parse_optional_list_setting(self.translators, lang, str)
            self.testers = parse_optional_list_setting(credits, "testers", str)
            self.packagers = parse_optional_list_setting(credits, "packagers", str)
            self.acknowledgements = parse_optional_list_setting(credits, "acknowledgements", str)

            # Check for unknown keys
            for key in credits:
                assert isinstance(key, str)
                warn(f"found unknown problem.yaml key: {key} in credits")


class ProblemSource:
    def __init__(self, name: str, url: Optional[str] = None):
        self.name = name
        self.url = url

    def __repr__(self) -> str:
        return self.name + (f" ({self.url})" if self.url else "")


class ProblemSources(list[ProblemSource]):
    def __init__(
        self,
        yaml_data: dict[str, Any],
        problem_settings: "ProblemSettings",
    ):
        # If problem.yaml uses the legacy version, do not support the new type of the `source` key.
        # If problem.yaml uses 2023-07-draft, prefer `source`, but also support `source_url` and warn for it.
        legacy_source_url = parse_optional_setting(yaml_data, "source_url", str)
        if problem_settings.is_legacy():
            source_name = parse_setting(yaml_data, "source", "")
            if legacy_source_url:
                self.append(ProblemSource(source_name, legacy_source_url))
        else:
            if legacy_source_url is not None:
                warn("problem.yaml: source_url is removed in 2023-07-draft, please use source.url")
            if "source" not in yaml_data:
                return
            if isinstance(yaml_data["source"], str):
                self.append(ProblemSource(parse_setting(yaml_data, "source", "")))
                return
            if isinstance(yaml_data["source"], dict):
                source = parse_setting(yaml_data, "source", dict[str, str]())
                self.append(
                    ProblemSource(
                        parse_setting(source, "name", ""),
                        parse_optional_setting(source, "url", str),
                    )
                )
                return
            if isinstance(yaml_data["source"], list):
                sources = parse_setting(yaml_data, "source", list[dict[str, str]]())
                for raw_source in sources:
                    source = parse_setting(raw_source, "source", dict[str, str]())
                    self.append(
                        ProblemSource(
                            parse_setting(source, "name", ""),
                            parse_optional_setting(source, "url", str),
                        )
                    )
                return
            warn("problem.yaml key 'source' does not have the correct type")


class ProblemLimits:
    def __init__(
        self,
        yaml_data: dict[str, Any],
        problem: "Problem",
        problem_settings: "ProblemSettings",
    ):
        assert isinstance(yaml_data, dict)

        # Known keys:
        # (defaults from https://icpc.io/problem-package-format/spec/2023-07-draft.html#limits)
        time_multipliers = parse_setting(yaml_data, "time_multipliers", dict[str, Any]())

        # If problem.yaml uses the legacy version, do not support the new keys.
        # If problem.yaml uses 2023-07-draft, prefer the new keys, but also support and warn for the old keys.
        legacy_ac_to_time_limit = parse_optional_setting(yaml_data, "time_multiplier", float)
        if problem_settings.is_legacy():
            self.ac_to_time_limit = legacy_ac_to_time_limit or 5.0
        else:
            if legacy_ac_to_time_limit is not None:
                warn(
                    "problem.yaml: limits.time_multiplier is removed in 2023-07-draft, please use limits.time_multipliers.ac_to_time_limit"
                )
            self.ac_to_time_limit = parse_setting(
                time_multipliers, "ac_to_time_limit", legacy_ac_to_time_limit or 2.0
            )

        legacy_time_limit_to_tle = parse_optional_setting(yaml_data, "time_safety_margin", float)
        if problem_settings.is_legacy():
            self.time_limit_to_tle = legacy_time_limit_to_tle or 2.0
        else:
            if legacy_time_limit_to_tle is not None:
                warn(
                    "problem.yaml: limits.time_safety_margin is removed in 2023-07-draft, please use limits.time_multipliers.time_limit_to_tle"
                )
            self.time_limit_to_tle = parse_setting(
                time_multipliers, "time_limit_to_tle", legacy_time_limit_to_tle or 1.5
            )

        # Check for unknown keys in time_multipliers
        for key in time_multipliers:
            assert isinstance(key, str)
            warn(f"found unknown problem.yaml key: {key} in limits.time_multipliers")

        # time_limit is required, but parse as optional to more easily handle the legacy_time_limit.
        time_limit = parse_optional_setting(yaml_data, "time_limit", float)  # in seconds
        self.time_resolution: float = parse_setting(yaml_data, "time_resolution", 1.0)
        self.memory: int = parse_setting(yaml_data, "memory", 2048)  # in MiB
        self.output: int = parse_setting(yaml_data, "output", 8)  # in MiB
        self.code: int = parse_setting(yaml_data, "code", 128)  # in KiB
        self.compilation_time: int = parse_setting(yaml_data, "compilation_time", 60)  # in seconds
        self.compilation_memory: int = parse_setting(
            yaml_data, "compilation_memory", 2048
        )  # in MiB
        self.validation_time: int = parse_setting(yaml_data, "validation_time", 60)  # in seconds
        self.validation_memory: int = parse_setting(yaml_data, "validation_memory", 2048)  # in MiB
        self.validation_output: int = parse_setting(yaml_data, "validation_output", 8)  # in MiB
        self.validation_passes: Optional[int] = parse_optional_setting(
            yaml_data, "validation_passes", int
        )

        # BAPCtools extensions:
        self.generator_time: int = parse_setting(yaml_data, "generator_time", 60)  # in seconds
        self.visualizer_time: int = parse_setting(yaml_data, "visualizer_time", 60)  # in seconds

        # Try to read deprecated ways of setting the time limit.
        def _get_legacy_time_limit():
            timelimit_path = problem.path / ".timelimit"
            if timelimit_path.is_file():
                if not problem_settings.is_legacy():
                    log("A .timelimit file is DEPRECATED. Use limits.time_limit instead.")
                return float(timelimit_path.read_text())

            domjudge_path = problem.path / "domjudge-problem.ini"
            if domjudge_path.is_file():
                log("domjudge-problem.ini is DEPRECATED. Use limits.time_limit instead.")
                for line in domjudge_path.read_text().splitlines():
                    key, var = map(str.strip, line.strip().split("="))
                    if (var[0] == '"' or var[0] == "'") and (var[-1] == '"' or var[-1] == "'"):
                        var = var[1:-1]
                    if key == "timelimit":
                        return float(var)

        # If limits.time_limit does not exist, attempt to use legacy_time_limit instead.
        legacy_time_limit = _get_legacy_time_limit()
        self.time_limit: float = time_limit or legacy_time_limit or 1.0
        self.time_limit_is_default: bool = time_limit is None and legacy_time_limit is None

        # Check for unknown keys
        for key in yaml_data:
            assert isinstance(key, str)
            warn(f"found unknown problem.yaml key: {key} in limits")

        # Override limmits by command line arguments.
        self.time_limit = config.args.time_limit or self.time_limit
        self.timeout = int(config.args.timeout or self.time_limit_to_tle * self.time_limit + 1)
        if config.args.timeout:
            self.validation_time = self.generator_time = self.visualizer_time = config.args.timeout
        if config.args.memory:
            self.memory = self.validation_memory = config.args.memory


class ProblemSettings:
    def __init__(
        self,
        yaml_data: dict[str, Any],
        problem: "Problem",
    ):
        assert isinstance(yaml_data, dict)

        if "name" in yaml_data and isinstance(yaml_data["name"], str):
            yaml_data["name"] = {"en": yaml_data["name"]}

        if "validator_flags" in yaml_data and isinstance(yaml_data["validator_flags"], str):
            yaml_data["validator_flags"] = shlex.split(yaml_data["validator_flags"])

        # Known keys:
        # (defaults from https://icpc.io/problem-package-format/spec/2023-07-draft.html#problem-metadata)
        self.problem_format_version: str = parse_setting(
            yaml_data, "problem_format_version", "legacy-icpc"
        )
        if not self.is_legacy() and self.problem_format_version != "2023-07-draft":
            fatal(f"problem_format_version {self.problem_format_version} not supported")

        if self.is_legacy():
            mode = parse_legacy_validation(parse_setting(yaml_data, "validation", "default"))
        else:
            if "validation" in yaml_data:
                warn(
                    "problem.yaml: 'validation' is removed in 2023-07-draft, please use 'type' instead"
                )
            mode = set(parse_setting(yaml_data, "type", "pass-fail").split(" "))
        self.interactive: bool = "interactive" in mode
        self.multi_pass: bool = "multi-pass" in mode
        self.custom_output: bool = (
            self.interactive
            or self.multi_pass
            or (
                "custom" in mode
                if self.is_legacy()
                # TODO #424: output_validator should be singular, but DOMjudge does not support this yet, so this should be fixed during export.
                else (problem.path / "output_validators").exists()
            )
        )

        self.name: dict[str, str] = parse_setting(yaml_data, "name", {"en": ""})
        self.uuid: str = parse_setting(yaml_data, "uuid", "")
        self.version: str = parse_setting(yaml_data, "version", "")
        self.credits = ProblemCredits(yaml_data, self)
        self.source = ProblemSources(yaml_data, self)
        self.license: str = parse_setting(yaml_data, "license", "unknown")
        self.rights_owner: str = parse_setting(yaml_data, "rights_owner", "")
        # Not implemented in BAPCtools. Should be a date, but we don't do anything with this anyway.
        self.embargo_until: str = parse_setting(yaml_data, "embargo-until", "")
        self.limits = ProblemLimits(parse_setting(yaml_data, "limits", {}), problem, self)
        # TODO: move to testdata.yaml
        self.validator_flags: list[str] = parse_setting(yaml_data, "validator_flags", [])
        self.keywords: str = parse_setting(yaml_data, "keywords", "")
        # Not implemented in BAPCtools. We always test all languges in langauges.yaml.
        self.languages: list[str] = parse_optional_list_setting(yaml_data, "languages", str)
        # Not yet implemented, pending https://github.com/Kattis/problem-package-format/issues/344
        self.constants: dict[str, Any] = parse_setting(yaml_data, "constants", {})

        # BAPCtools extensions:
        self.verified: Optional[str] = parse_optional_setting(yaml_data, "verified", str)
        self.comment: Optional[str] = parse_optional_setting(yaml_data, "comment", str)

        # check for unknown keys
        for key in yaml_data:
            assert isinstance(key, str)
            warn(f"found unknown problem.yaml key: {key}")

        # checks
        if not is_uuid(self.uuid):
            warn(f"invalid uuid: {self.uuid}")
        if self.license not in config.KNOWN_LICENSES:
            warn(f"invalid license: {self.license}")
            self.license = "unknown"

    def is_legacy(self):
        return self.problem_format_version.startswith("legacy")


# A problem.
class Problem:
    _SHORTNAME_REGEX_STRING: Final[str] = "^[a-z0-9]+$"
    _SHORTNAME_REGEX: Final[re.Pattern[str]] = re.compile(_SHORTNAME_REGEX_STRING)

    def __init__(self, path: Path, tmpdir: Path, label: Optional[str] = None):
        # The problem name/shortname, which is the name of the directory and used as a display name.
        self.name = path.resolve().name
        # The Path of the problem directory.
        self.path = path
        self.tmpdir: Path = tmpdir / self.name
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        # Read problem.yaml and domjudge-problem.ini into self.settings Namespace object.
        self._read_settings()

        # Some caches.
        self._testcases = dict[
            tuple[Optional[validate.Mode], bool, bool], list[testcase.Testcase]
        ]()
        self._submissions: Optional[list[run.Submission] | Literal[False]] = None
        self._validators_cache = dict[  # The "bool" is for "check_constraints"
            tuple[type[validate.AnyValidator], bool], list[validate.AnyValidator]
        ]()
        self._validators_warn_cache = set[tuple[type[validate.AnyValidator], bool]]()
        self._programs = dict[Path, "Program"]()
        self._program_callbacks = dict[Path, list[Callable[["Program"], None]]]()
        # Dictionary from path to parsed file contents.
        # TODO #102: Add type for testdata.yaml (typed Namespace?)
        self._testdata_yamls = dict[Path, dict[str, Any]]()
        self._testdata_lock = threading.Lock()

        # The label for the problem: A, B, A1, A2, X, ...
        self.label = label

        # TODO: transform this into nice warnings
        assert path.is_dir()
        if not Problem._SHORTNAME_REGEX.match(self.name):
            warn(
                f"Problem has a bad shortname: {self.name} does not match {self._SHORTNAME_REGEX_STRING}"
            )

        self.statement_languages = self._determine_statement_languages()

    def _determine_statement_languages(self):
        """Determine the languages that are both mentioned in the problem.yaml under name
        and have a corresponding problem statement.

        If problem.yaml's name key is a string, convert into dict; assume `en` as default language.
        """
        yamllangs = set(self.settings.name)
        texlangs = set(
            path.suffixes[0][1:] for path in glob(self.path, "problem_statement/problem.*.tex")
        )
        for lang in texlangs - yamllangs:
            error(
                f"{self.name}: Found problem.{lang}.tex, but no corresponding name in problem.yaml."
            )
        for lang in yamllangs - texlangs:
            error(
                f"{self.name}: Found name for language {lang} in problem.yaml, but not problem.{lang}.tex."
            )
        # Check that names in problem.yaml and \problemname{} in problem.*.tex agree:
        for lang in texlangs & yamllangs:
            unnormalised_yamlname = self.settings.name[lang]
            yamlname = " ".join(unnormalised_yamlname.split())
            with open(self.path / "problem_statement" / f"problem.{lang}.tex") as texfile:
                match texname := latex.get_argument_for_command(texfile, "problemname"):
                    case None:
                        error(rf"No \problemname found in problem.{lang}.tex")
                        continue
                    case "":
                        continue
                    case r"\problemyamlname":
                        warn(
                            rf"Prefer using \problemname{{}} instead of \problemname{{\problemyamlname}} in problem.{lang}.tex"
                        )
                        continue
                    case s if "\\" in s or "_" in s or "^" in s:
                        # texname contains markup, like "CO_2" or "\emph{Hello}":
                        # Assume authors know what they're doing
                        continue
                    case s if s != yamlname:
                        warn(
                            f"Problem titles in problem.{lang}.tex ({texname})"
                            + f" and problem.yaml ({yamlname}) differ;"
                            + r" consider using \problemname{}."
                        )
        return sorted(texlangs & yamllangs)

    def _read_settings(self):
        # parse problem.yaml
        yaml_path = self.path / "problem.yaml"
        if has_ryaml:
            try:
                yaml_data = read_yaml_settings(yaml_path)
            except ruamel.yaml.scanner.ScannerError:
                fatal(f"Make sure {self.name}/problem.yaml does not contain any more {{% ... %}}.")
        else:
            yaml_data = read_yaml_settings(yaml_path)
        yaml_data = yaml_data or {}

        if "uuid" not in yaml_data:
            uuid = generate_problem_uuid()
            yaml_data["uuid"] = uuid
            raw = yaml_path.read_text().rstrip()
            raw += f"\n# uuid added by BAPCtools\nuuid: '{uuid}'\n"
            yaml_path.write_text(raw)
            log("Added new UUID to problem.yaml")

        self.settings = ProblemSettings(yaml_data, self)

        # Aliasing fields makes life easier for us 😛
        self.limits: ProblemLimits = self.settings.limits
        self.interactive: bool = self.settings.interactive
        self.multi_pass: bool = self.settings.multi_pass
        self.custom_output: bool = self.settings.custom_output

        # Handle dependencies...
        has_validation_passes = self.limits.validation_passes is not None
        if self.multi_pass and not has_validation_passes:
            self.limits.validation_passes = 2
        if not self.multi_pass and has_validation_passes:
            warn("limit: validation_passes is only used for multi_pass problems. SKIPPED.")

    def _parse_testdata_yaml(p, path, bar):
        assert path.is_relative_to(p.path / "data")
        for dir in [path] + list(path.parents):
            # Do not go above the data directory.
            if dir == p.path:
                return

            f = dir / "testdata.yaml"
            if not f.is_file() or f in p._testdata_yamls:
                continue
            with p._testdata_lock:
                if f not in p._testdata_yamls:
                    p._testdata_yamls[f] = flags = read_yaml(f, plain=True)

                    # verify testdata.yaml
                    for k in flags:
                        match k:
                            case "output_validator_flags":
                                if not isinstance(flags[k], str):
                                    bar.error(
                                        "ouput_validator_flags must be string",
                                        resume=True,
                                        print_item=False,
                                    )
                            case "input_validator_flags":
                                if not isinstance(flags[k], (str, dict)):
                                    bar.error(
                                        "input_validator_flags must be string or map",
                                        resume=True,
                                        print_item=False,
                                    )
                                if isinstance(flags[k], dict):
                                    input_validator_names = set(
                                        val.name for val in p.validators(validate.InputValidator)
                                    )
                                    for name in set(flags[k]) - input_validator_names:
                                        bar.warn(
                                            f"Unknown input validator {name}; expected {input_validator_names}",
                                            print_item=False,
                                        )
                            case "grading" | "run_samples":
                                bar.warn(f"{k} not implemented in BAPCtools", print_item=False)
                            case _:
                                path = f.relative_to(p.path / "data")
                                bar.warn(f'Unknown key "{k}" in {path}', print_item=False)
            # Do not go above the data directory.
            if dir == p.path / "data":
                break

    def get_testdata_yaml(p, path, key, bar, name=None) -> str | None:
        """
        Find the testdata flags applying at the given path for the given key.
        If necessary, walk up from `path` looking for the first testdata.yaml file that applies,

        Side effects: parses and caches the file.

        Arguments
        ---------
        path: absolute path (a file or a directory)
        key: The testdata.yaml key to look for, either of 'input_validator_flags', 'output_validator_flags', or 'grading'.
            'grading' is not implemented
        name: If key == 'input_validator_flags', optionally the name of the input validator

        Returns:
        --------
        string or None if no testdata.yaml is found.
        TODO: when 'grading' is supported, it also can return dict
        """
        if key not in ["input_validator_flags", "output_validator_flags"]:
            raise NotImplementedError(key)
        if key != "input_validator_flags" and name is not None:
            raise ValueError(
                f"Only input validators support flags by validator name, got {key} and {name}"
            )

        # parse and cache testdata.yaml
        p._parse_testdata_yaml(path, bar)

        # extract the flags
        for dir in [path] + list(path.parents):
            # Do not go above the data directory.
            if dir == p.path:
                return None

            f = dir / "testdata.yaml"
            if f not in p._testdata_yamls:
                continue
            flags = p._testdata_yamls[f]
            if key in flags:
                if key == "output_validator_flags":
                    if not isinstance(flags[key], str):
                        bar.error("ouput_validator_flags must be string")
                    return flags[key]

                if key == "input_validator_flags":
                    if not isinstance(flags[key], (str, dict)):
                        bar.error("input_validator_flags must be string or map")
                    if isinstance(flags[key], str):
                        return flags[key]
                    elif name in flags[key]:
                        return flags[key][name]

        return None

    def testcases(
        p,
        *,
        mode: Optional[validate.Mode] = None,
        needans=True,
        only_samples=False,
    ) -> Sequence[testcase.Testcase]:
        only_samples = config.args.samples or only_samples

        key = (mode, needans, only_samples)
        if key in p._testcases is not None:
            return p._testcases[key]

        in_paths = None
        if config.args.testcases:
            if only_samples:
                assert False
            # Deduplicate testcases with both .in and .ans.
            in_paths = []
            for t in config.args.testcases:
                t = resolve_path_argument(p, t, "data", suffixes=[".in"])
                if t:
                    # When running from contest level, the testcase must be inside the problem.
                    if config.level != "problemset" or is_relative_to(p.path, t):
                        if t.is_dir():
                            in_paths += glob(t, "**/*.in")
                        else:
                            in_paths.append(t)

            in_paths = list(set(in_paths))
        elif mode is not None:
            in_paths = []
            for prefix in {
                validate.Mode.INPUT: ["secret", "sample"],
                validate.Mode.ANSWER: ["secret", "sample"],
                validate.Mode.INVALID: config.INVALID_CASE_DIRECTORIES,
            }[mode]:
                in_paths += glob(p.path, f"data/{prefix}/**/*.in")
        else:
            in_paths = list(glob(p.path, "data/sample/**/*.in"))
            if not only_samples:
                in_paths += list(glob(p.path, "data/secret/**/*.in"))

        testcases = []
        for f in in_paths:
            t = testcase.Testcase(p, f, print_warn=True)
            if (
                (p.interactive or p.multi_pass)
                and mode == validate.Mode.INVALID
                and t.root in ["invalid_answers", "invalid_outputs"]
            ):
                msg = ""
                if p.interactive:
                    msg += " interactive"
                if p.multi_pass:
                    msg += " multi-pass"
                warn(f"Found file {f} for {mode} validation in{msg} problem. Skipping.")
                continue
            if needans and not t.ans_path.is_file():
                if t.root != "invalid_inputs":
                    warn(f"Found input file {f} without a .ans file. Skipping.")
                    continue
            testcases.append(t)
        testcases.sort(key=lambda t: t.name)

        if len(testcases) == 0:
            ans = " with answer" if needans and mode != validate.Mode.INVALID else ""
            val = f" for {mode} validation" if mode is not None else ""
            # TODO perhaps move this log to the use site?
            (log if mode == validate.Mode.INVALID else warn)(
                f"Didn't find any testcases{ans}{val} in problem {p.name}. Skipping."
            )

        p._testcases[key] = testcases
        return testcases

    # Returns a list of:
    # - (Path, Path): (.in, .ans) pair
    # - (Path, Path): (.in.statement, .ans.statement) pair
    # -  Path       :  .interaction file
    def statement_samples(p) -> list[Path | tuple[Path, Path]]:
        statement_in_paths = list(glob(p.path, "data/sample/**/*.in.statement"))
        interaction_paths = list(glob(p.path, "data/sample/**/*.interaction"))

        # Make sure that .in.statement files are not mixed with .interaction files.
        for in_path in interaction_paths:
            if in_path.with_suffix(".in.statement").is_file():
                warn(
                    f"Do not mix .in.statement files and .interaction files with the same basename in {p}."
                )

        # A .in may be shadowed by either .in.statement or .interaction, in which case the .in itself is not shown in the PDF.
        in_paths = []
        for in_path in list(glob(p.path, "data/sample/**/*.in")):
            if in_path.with_suffix(".in.statement").is_file():
                continue
            if in_path.with_suffix(".interaction").is_file():
                continue
            in_paths.append(in_path)

        # .interaction files cannot be mixed with .in/.ans pairs.
        if len(interaction_paths) != 0 and len(in_paths) + len(statement_in_paths) != 0:
            warn(f"Do not mix .interaction files with .in/.ans files in {p}.")

        # Non-interactive and Non-multi-pass problems should not have .interaction files.
        # On the other hand, interactive problems are allowed to have .{in,ans}.statement files,
        # so that they can emulate a non-interactive problem with on-the-fly generated input.
        if not p.interactive and not p.multi_pass:
            if len(interaction_paths) != 0:
                warn(
                    f"Non-interactive/Non-multi-pass problem {p.name} should not have data/sample/*.interaction files."
                )
            interaction_paths = []

        testcases = list[Path | tuple[Path, Path]]()
        for in_path in in_paths:
            ans_path = in_path.with_suffix(".ans")
            if not ans_path.is_file():
                warn(f"Found input file {in_path} without a .ans file. Skipping.")
                continue
            testcases.append((in_path, ans_path))

        for in_path in statement_in_paths:
            # first remove .statement, then replace .in with .ans.statement
            ans_path = in_path.with_suffix("").with_suffix(".ans.statement")
            if not ans_path.is_file():
                warn(f"Found input file {in_path} without a .ans.statement file. Skipping.")
                continue
            testcases.append((in_path, ans_path))

        for interaction_path in interaction_paths:
            testcases.append(interaction_path)

        testcases.sort()

        return testcases

    # Returns the list of submissions passed as command-line arguments, or the list of accepted submissions by default.
    def selected_or_accepted_submissions(problem) -> list["run.Submission"]:
        submissions = problem.submissions()
        if not submissions:
            return []
        if config.args.submissions:
            return submissions
        else:
            return [s for s in submissions if s.expected_verdicts == [verdicts.Verdict.ACCEPTED]]

    def submissions(problem) -> list["run.Submission"] | Literal[False]:
        if problem._submissions is not None:
            if problem._submissions is False:
                return False
            else:
                return problem._submissions.copy()

        paths = []
        if config.args.submissions:

            def add(s):
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

        # - first all submission with just one verdict (sorted by that verdict)
        # - then by subdir
        # - then by list of verdicts
        # - then by name
        def submissions_key(x):
            if len(x.expected_verdicts) == 1:
                return (1, x.expected_verdicts[0], x.name)
            else:
                return (len(x.expected_verdicts), x.subdir, x.expected_verdicts, x.name)

        programs.sort(key=submissions_key)

        bar = ProgressBar("Build submissions", items=programs)

        def build_program(p):
            localbar = bar.start(p)
            p.build(localbar)
            localbar.done()

        parallel.run_tasks(build_program, programs)

        bar.finalize(print_done=False)

        # Filter out broken submissions.
        problem._submissions = [p for p in programs if p.ok]

        if len(problem._submissions) == 0:
            problem._submissions = False
            return False

        assert isinstance(problem._submissions, list)
        return problem._submissions.copy()

    def validators(
        problem,
        cls: type[validate.AnyValidator],
        check_constraints=False,
        strict=False,
        print_warn=True,
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
        if not strict and cls == validate.AnswerValidator:
            validators = validators + problem._validators(
                validate.OutputValidator, check_constraints
            )

        # Check that the proper number of validators is present
        # do this after handling the strict flag but dont warn every time
        if print_warn:
            key = (cls, check_constraints)
            if key not in problem._validators_warn_cache:
                problem._validators_warn_cache.add(key)
                match cls, len(validators):
                    case validate.InputValidator, 0:
                        warn("No input validators found.")
                    case validate.AnswerValidator, 0:
                        warn("No answer validators found")
                    case validate.OutputValidator, l if l != 1:
                        error(f"Found {len(validators)} output validators, expected exactly one.")

        build_ok = all(v.ok for v in validators)

        # All validators must build.
        # TODO Really? Why not at least return those that built?
        return validators if build_ok else []

    def _validators(
        problem, cls: type[validate.AnyValidator], check_constraints=False
    ) -> list[validate.AnyValidator]:
        key = (cls, check_constraints)
        if key in problem._validators_cache:
            return problem._validators_cache[key]

        assert hasattr(cls, "source_dirs")
        # TODO #424: We should not support multiple output validators inside output_validator/.
        paths = [p for source_dir in cls.source_dirs for p in glob(problem.path / source_dir, "*")]

        # Handle default output validation
        if cls == validate.OutputValidator:
            if problem.settings.is_legacy() and not problem.custom_output and paths:
                error("Validation is default but custom output validator exists (ignoring it)")
                paths = []
            if not paths:
                if problem.custom_output:
                    fatal("Problem validation type requires output_validators/")
                paths = [config.TOOLS_ROOT / "support" / "default_output_validator.cpp"]

        # TODO: Instead of checking file contents, maybe specify this in generators.yaml?
        def has_constraints_checking(f):
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
        validators = [
            cls(
                problem,
                path,
                skip_double_build_warning=skip_double_build_warning,
                check_constraints=check_constraints,
            )
            for path in paths
        ]
        bar = ProgressBar(f"Building {cls.validator_type} validator", items=validators)

        def build_program(p):
            localbar = bar.start(p)
            p.build(localbar)
            localbar.done()

        parallel.run_tasks(build_program, validators)
        bar.finalize(print_done=False)

        problem._validators_cache[key] = validators
        return validators

    # get all testcses and submissions and prepare the output validator
    def prepare_run(problem):
        testcases = problem.testcases()
        if not testcases:
            return False

        if problem.interactive:
            validators = problem.validators(validate.OutputValidator)
            if not validators:
                return False

        # Pre build the output validator to prevent nested ProgressBars.
        if problem.validators(validate.OutputValidator) is False:
            return False

        submissions = problem.submissions()
        if not submissions:
            return False

        return testcases, submissions

    @staticmethod
    def run_some(testcases, submissions):
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
    def run_submissions(problem):
        ts_pair = problem.prepare_run()
        if not ts_pair:
            return False
        testcases, submissions = ts_pair
        ok, verdict_table = Problem.run_some(testcases, submissions)

        if config.args.table:
            Problem._print_table(verdict_table.results, testcases)
        elif config.args.overview and not config.args.tree:
            verdict_table.print(force=True, new_lines=1)

        return ok

    # Takes a list of submissions and runs them against the chosen testcases.
    # Instead of validating the output, this function just prints all output to the
    # terminal.
    # Note: The CLI only accepts one submission.
    def test_submissions(problem):
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
    def _print_table(verdict_table, testcases):
        # Begin by aggregating bitstrings for all testcases, and find bitstrings occurring often (>=config.TABLE_THRESHOLD).
        def single_verdict(row, testcase):
            assert row[testcase.name] is not None
            if row[testcase.name] is not False:
                return verdicts.to_char(row[testcase.name])
            else:
                return f"{Style.DIM}-{Style.RESET_ALL}"

        def make_verdict(tc):
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

        print(
            "\nVerdict analysis table. Submissions are ordered per column as above. Higher "
            "scores indicate they are critical to break some submissions. Only cases breaking at least one submission are listed.",
            file=sys.stderr,
        )
        fail = (
            verdicts.to_char(verdicts.Verdict.WRONG_ANSWER)
            + verdicts.to_char(verdicts.Verdict.TIME_LIMIT_EXCEEDED)
            + verdicts.to_char(verdicts.Verdict.RUNTIME_ERROR)
        )
        print(f"{fail}: submission fails testcase", file=sys.stderr)
        print(
            f"{verdicts.to_char(verdicts.Verdict.ACCEPTED)}: submission passes testcase\n",
            file=sys.stderr,
        )

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
            print(f"{Fore.CYAN}{name}{Style.RESET_ALL}:{padding}", end=" ", file=sys.stderr)

            color = Style.RESET_ALL
            if len(scores_list) > 6 and scores[case.name] >= scores_list[-6]:
                color = Fore.YELLOW
            if len(scores_list) > 3 and scores[case.name] >= scores_list[-3]:
                color = Fore.RED
            resultant = make_verdict(case)
            print(resultant, end="  ", file=sys.stderr)
            print(f"{color}{scores[case.name]:0.3f}{Style.RESET_ALL}  ", end="", file=sys.stderr)
            if resultant in resultant_id:
                print(str.format("(Type {})", resultant_id[resultant]), end="", file=sys.stderr)
            print(end="\n", file=sys.stderr)

    def reset_testcase_hashes(self):
        self._testcase_hashes = {}

    # Returns None for new testcases or the Testcase object it equals.
    def matches_existing_testcase(self, t):
        if t.root in ["invalid_input", "invalid_answer"]:
            return None
        h = hash_file_content(t.in_path)
        if h in self._testcase_hashes:
            return self._testcase_hashes[h]
        self._testcase_hashes[h] = t
        return None

    def validate_data(problem, mode: validate.Mode, constraints: dict | bool | None = None) -> bool:
        """Validate aspects of the test data files.

        Arguments:
            mode: validate.Mode.INPUT | validate.Mode.ANSWER | validate.Mode.INVALID
            constraints: True | dict | None. True means "do check constraints but discard the result."
                False: TODO is this ever used?
        Return:
            True if all validation was successful. Successful validation includes, e.g.,
            correctly rejecting invalid inputs.
        """
        if (problem.interactive or problem.multi_pass) and mode == validate.Mode.ANSWER:
            if problem.validators(validate.AnswerValidator, strict=True, print_warn=False):
                msg = ""
                if problem.interactive:
                    msg += " interactive"
                if problem.multi_pass:
                    msg += " multi-pass"
                log(f"Not running answer_validators for{msg} problems.")
            return True

        action = (
            "Invalidation"
            if mode == validate.Mode.INVALID
            else (
                f"Collecting {mode} constraints"
                if constraints
                else f"{str(mode).capitalize()} validation"
            )
        )

        testcases = problem.testcases(mode=mode)
        return problem._validate_data(mode, constraints, action, testcases)

    def validate_invalid_extra_data(p) -> bool:
        base_path = p.tmpdir / "invalid_data"
        # pick at most first 3 samples (assuming they are valid and have .ans)
        # also add a dummy entry to always run generators that don't read or copy anything from a valid testcase
        samples = sorted(glob(p.path, "data/sample/**/*.in"))[:3] + [None]

        # validator, dir, read, write, copy
        validators: list[tuple[type[validate.AnyValidator], str, str, str, list[str]]] = [
            (validate.InputValidator, "invalid_inputs", ".in", ".in", []),
            (validate.AnswerValidator, "invalid_answers", ".ans", ".ans", [".in"]),
            (validate.OutputValidator, "invalid_outputs", ".ans", ".out", [".in", ".ans"]),
        ]

        testcases: list[testcase.Testcase] = []
        for i, sample in enumerate(samples):
            used_sample = False
            for cls, directory, read, write, copy in validators:
                if (p.interactive or p.multi_pass) and cls != validate.InputValidator:
                    continue
                if not p.validators(cls, strict=True, print_warn=False):
                    continue
                if any(sample is None or not sample.with_suffix(ext).exists() for ext in copy):
                    continue

                for name, data, supported_cls in validator_tests.GENERATORS:
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
        verbose(f"writing generated invalid testcases to: {base_path}")

        return p._validate_data(
            validate.Mode.INVALID, None, "Generic Invalidation", testcases, True
        )

    def _validate_data(
        problem,
        mode: validate.Mode,
        constraints: dict | bool | None,
        action: str,
        testcases: Sequence[testcase.Testcase],
        extra: bool = False,
    ) -> bool:
        # If there are no testcases, validation succeeds
        if not testcases:
            return True

        if constraints is True:
            constraints = {}
        assert constraints is None or isinstance(constraints, dict)

        # Pre-build the relevant Validators so as to avoid clash with ProgressBar bar below
        # Also, pick the relevant testcases
        check_constraints = constraints is not None
        match mode:
            case validate.Mode.INPUT:
                problem.validators(validate.InputValidator, check_constraints=check_constraints)
            case validate.Mode.ANSWER:
                assert not problem.interactive
                assert not problem.multi_pass
                problem.validators(validate.AnswerValidator, check_constraints=check_constraints)
            case validate.Mode.INVALID:
                problem.validators(validate.InputValidator)
                if not problem.interactive and not problem.multi_pass:
                    problem.validators(validate.AnswerValidator)
            case _:
                raise ValueError(mode)

        success = True

        problem.reset_testcase_hashes()

        # validate the testcases
        bar = ProgressBar(action, items=[t.name for t in testcases])

        def process_testcase(testcase):
            nonlocal success

            localbar = bar.start(testcase.name)

            if (
                mode == validate.Mode.INPUT
                and not testcase.in_path.is_symlink()
                and not testcase.root == "invalid_answers"
                and not testcase.root == "invalid_outputs"
                and not extra
            ):
                t2 = problem.matches_existing_testcase(testcase)
                if t2 is not None:
                    localbar.warn(
                        f"Duplicate testcase: identical to {t2.name}. If this is intentional use symlinks/count/includes."
                    )
                    localbar.done()
                    return

            ok = testcase.validate_format(
                mode, bar=localbar, constraints=constraints, warn_instead_of_error=extra
            )
            success &= ok
            localbar.done(ok)

        parallel.run_tasks(process_testcase, testcases)

        bar.finalize(print_done=True)

        # Make sure all constraints are satisfied.
        if constraints:
            for loc, value in sorted(constraints.items()):
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

    def determine_time_limit(problem):
        ts_pair = problem.prepare_run()
        if not ts_pair:
            return False
        testcases, submissions = ts_pair

        problem.limits.time_limit = config.args.timeout or 60
        problem.limits.time_limit_is_default = False
        problem.limits.timeout = problem.limits.time_limit

        ok = True

        def run_all(select_verdict, select):
            nonlocal ok

            cur_submissions = [s for s in submissions if select_verdict(s.expected_verdicts)]

            if len(cur_submissions) == 0:
                return None, None, None

            cur_ok, verdict_table = Problem.run_some(testcases, cur_submissions)
            ok &= cur_ok

            def get_slowest(result):
                slowest_pair = result.slowest_testcase()
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

        problem.limits.time_limit = problem.limits.time_resolution * math.ceil(
            duration * problem.limits.ac_to_time_limit / problem.limits.time_resolution
        )
        safety_time_limit = problem.limits.time_limit * problem.limits.time_limit_to_tle
        problem.limits.timeout = int(safety_time_limit * problem.limits.time_limit_to_tle + 1)

        if config.args.write:
            if not has_ryaml:
                warn("ruamel.yaml library not found. Please update the time limit fields manually.")
            else:
                yaml_path = problem.path / "problem.yaml"
                problem_yaml = read_yaml(yaml_path)
                if problem_yaml is None:
                    problem_yaml = ruamel.yaml.comments.CommentedMap()
                limits = ryaml_get_or_add(problem_yaml, "limits")
                limits["time_limit"] = problem.limits.time_limit
                write_yaml(problem_yaml, problem.path / "problem.yaml")

        print()
        message(f"{duration:.3f}s @ {testcase} ({submission})", "slowest AC")
        message(
            f"{problem.limits.time_limit}s >= {duration:.3f}s * {problem.limits.ac_to_time_limit}",
            "time limit",
        )
        message(
            f"{safety_time_limit}s >= {problem.limits.time_limit}s * {problem.limits.time_limit_to_tle}",
            "safety limit",
        )
        message(
            f"{problem.limits.timeout}s >= {problem.limits.time_limit}s * {problem.limits.time_limit_to_tle}²",
            "timeout",
        )
        print()

        submission, testcase, duration = run_all(
            lambda vs: vs == [verdicts.Verdict.TIME_LIMIT_EXCEEDED], min
        )
        if submission is not None:
            print()
            message(f"{duration:.3f}s @ {testcase} ({submission})", "fastest TLE")
            if duration <= problem.limits.time_limit:
                error("TLE submission runs within time limit")
            elif duration <= safety_time_limit:
                warn("TLE submission runs within safety margin")
            elif duration >= problem.limits.timeout:
                log(f"No TLE submission finished within {problem.limits.timeout}s")
            print()
        else:
            log("No TLE submissions found")

        if config.args.all:
            submission, testcase, duration = run_all(
                lambda vs: vs != [verdicts.Verdict.ACCEPTED]
                and vs != [verdicts.Verdict.TIME_LIMIT_EXCEEDED],
                max,
            )
            if submission is not None:
                if duration > problem.limits.time_limit:
                    warn("Non TLE submission timed out")
                else:
                    log("All non TLE submission finished within time limit")
        return ok
