import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Optional, TYPE_CHECKING

from bapctools import config
from bapctools.testcase import Testcase
from bapctools.util import error, fatal, read_yaml, warn, YamlParser
from bapctools.verdicts import Verdict

if TYPE_CHECKING:
    from bapctools.problem import Problem
    from bapctools.run import Submission


class Person:
    def __init__(self, source: str, yaml_data: str | dict[object, object], parent_path: str):
        if isinstance(yaml_data, dict):
            parser = YamlParser(source, yaml_data, parent_path)
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

    @staticmethod
    def extract_optional_persons(source: YamlParser, key: str) -> list["Person"]:
        key_path = f"{source.parent_path}.{key}"
        if key in source.yaml:
            value = source.yaml.pop(key)
            if value is None:
                return []
            if isinstance(value, (str, dict)):
                return [Person(source.source, value, key_path)]
            if isinstance(value, list):
                if not all(isinstance(v, (str, dict)) for v in value):
                    warn(
                        f"some values for key `{key_path}` in {source.source} have invalid type. SKIPPED."
                    )
                    return []
                if not value:
                    warn(f"value for `{key_path}` in {source.source} should not be an empty list.")
                return [Person(source.source, v, f"{key_path}[{i}]") for i, v in enumerate(value)]
            warn(f"incompatible value for key `{key_path}` in {source.source}. SKIPPED.")
        return []


VERDICTS: Final[Sequence[Verdict]] = [
    Verdict.ACCEPTED,
    Verdict.WRONG_ANSWER,
    Verdict.TIME_LIMIT_EXCEEDED,
    Verdict.RUNTIME_ERROR,
]
KNOWN_VERDICTS: Final[Mapping[str, Verdict]] = {v.short(): v for v in VERDICTS}


def _compile_glob(glob: str) -> re.Pattern[str]:
    # dir/ and dir should match the same
    if glob.endswith("/"):
        glob = glob[:-1]
    # TODO: does this properly handle brace expansion?
    # TODO: what should happen for nested braces
    parts = re.split("{([^{}]*)}", glob)
    for i, part in enumerate(parts):
        part = re.escape(part)
        if i % 2 != 0:
            part = f"({'|'.join(re.escape(p) for p in part.split(','))})"
        parts[i] = part
    glob = "".join(parts)
    # stars match anything exept /
    glob = glob.replace(re.escape("*"), "[^/]*")
    # match from start and only match complete directories
    glob = f"^{glob}(/|$)"
    return re.compile(glob)


class TestcaseExpectation:
    def __init__(self, parser: Optional[YamlParser] = None, test_case_glob: Optional[str] = None):
        if parser is None:
            parser = YamlParser("internal", {})

        self.test_case_glob: Optional[str] = test_case_glob
        self.test_case_regex: Optional[re.Pattern[str]] = None
        if test_case_glob is not None:
            self.test_case_regex = _compile_glob(test_case_glob)

        def extract_verdicts(key: str, default: set[Verdict] = set(VERDICTS)) -> set[Verdict]:
            verdicts = parser.extract_optional_list(key, str)
            if not verdicts:
                return default
            if any(v not in KNOWN_VERDICTS for v in verdicts):
                warn(
                    f"some values for key `{parser.parent_path}.{key}` in {parser.source} are unknown. SKIPPED."
                )
                return default
            return {KNOWN_VERDICTS[v] for v in verdicts}

        self.permitted: set[Verdict] = extract_verdicts("permitted")
        self.required: set[Verdict] = extract_verdicts("required", self.permitted)
        if not self.required.issubset(self.permitted):
            missing = ",".join(v.short() for v in self.required - self.permitted)
            warn(f"`{parser.parent_path}` has [{missing}] as required but not as permitted")

        if "score" in parser.yaml:
            # Not implemented
            # self.score: Optional[float | tuple[float, float]] = 0
            is_list = isinstance(parser.yaml["score"], list)
            score = parser.extract_optional_list("score", float)
            if len(score) not in [0, 2 if is_list else 1]:
                warn(
                    f"(`{parser.parent_path}.score` must be a single float or a list of two floats.)"
                )
            warn("Scoring is not implemented in BAPCtools.")

        self.message: Optional[str] = parser.extract_optional("message", str)
        self.lower_time_limit: bool = Verdict.TIME_LIMIT_EXCEEDED not in self.permitted
        self.upper_time_limit: bool = {Verdict.TIME_LIMIT_EXCEEDED} == self.required
        self.allowed_for_time_limit: bool = True
        use_for_time_limit = parser.pop("use_for_time_limit")
        if use_for_time_limit not in [True, None]:
            self.lower_time_limit = use_for_time_limit == "lower"
            self.upper_time_limit = use_for_time_limit == "upper"
            if use_for_time_limit not in [True, False, "lower", "upper"]:
                warn(
                    f"`{parser.parent_path}.use_for_time_limit` must be bool, `lower`, or `upper`. SKIPPED."
                )
        if self.lower_time_limit and self.upper_time_limit:
            error(f"`{parser.parent_path}` is used for upper and lower time limit!")

    def matches(self, testcase: Testcase) -> bool:
        if self.test_case_regex is None:
            return True
        return self.test_case_regex.match(testcase.name) is not None


class SubmissionExpectation:
    def __init__(self, submission_glob: str, yaml_data: dict[object, object]) -> None:
        self.submission_glob: str = submission_glob
        self.submission_regex: re.Pattern[str] = _compile_glob(submission_glob)

        parser = YamlParser("submissions.yaml", yaml_data, submission_glob)

        self.language: Optional[str] = parser.extract_optional("language", str)
        self.entrypoint: Optional[str] = parser.extract_optional("entrypoint", str)
        if self.entrypoint is not None:
            warn("entrypoint is not used by BAPCtools.")
        self.authors: list[Person] = Person.extract_optional_persons(parser, "authors")
        self.model_solution: bool = parser.extract("model_solution", False)

        self.expectations: list[TestcaseExpectation] = [TestcaseExpectation(parser)]
        for key in list(parser.yaml):
            if not isinstance(key, str):
                continue
            # TODO is se* allowed here? should we just do no check at all?
            if not key.startswith("sample") and not key.startswith("secret"):
                continue
            self.expectations.append(TestcaseExpectation(parser.extract_parser(key), key))
        parser.check_unknown_keys()

    def matches(self, submission: "Submission") -> bool:
        return self.submission_regex.match(submission.name) is not None

    def all_matches(self, testcase: Optional[Testcase] = None) -> list[TestcaseExpectation]:
        # TODO: should we return all here? there could be expectations that match no test case at all?
        if testcase is None:
            return self.expectations
        # TODO: warn if if there is no match?
        return [e for e in self.expectations if e.matches(testcase)]

    def all_permitted(self, testcase: Optional[Testcase] = None) -> set[Verdict]:
        permitted = set(VERDICTS)
        for e in self.all_matches(testcase):
            permitted &= e.permitted
        return permitted


class Expectation:
    def __init__(self, problem: "Problem") -> None:
        self.expectations: dict[str, SubmissionExpectation] = {}
        self._combined: dict[Path, SubmissionExpectation] = {}

        files = [
            config.RESOURCES_ROOT / "config" / "submissions.yaml",
            problem.path / "submissions" / "submissions.yaml",
        ]
        for file in files:
            if not file.is_file():
                continue
            yaml_data = read_yaml(file)
            if not isinstance(yaml_data, dict):
                fatal("could not parse submissions.yaml.")
            for submission_glob, expectation in yaml_data.items():
                if not isinstance(submission_glob, str):
                    error("keys in submissions.yaml must be strings. SKIPPED.")
                    continue
                if not isinstance(expectation, dict):
                    error(f"invalid entry {expectation} in submissions.yaml. SKIPPED.")
                    continue
                self.expectations[submission_glob] = SubmissionExpectation(
                    submission_glob, expectation
                )

    def all_matches(self, submission: "Submission") -> SubmissionExpectation:
        if submission.path in self._combined:
            return self._combined[submission.path]

        languages = set()
        entrypoints = set()
        authors = set()

        combined = SubmissionExpectation(submission.name, {})
        found_match = False
        for expectation in self.expectations.values():
            if not expectation.matches(submission):
                continue
            found_match = True
            if expectation.language is not None:
                languages.add(expectation.language)
            if expectation.entrypoint is not None:
                entrypoints.add(expectation.entrypoint)
            if expectation.authors:
                authors.add(expectation.authors)
            combined.model_solution |= expectation.model_solution
            combined.expectations += expectation.expectations

        combined.language = min(languages, default=combined.language)
        combined.entrypoint = min(entrypoints, default=combined.entrypoint)
        combined.authors = min(authors, default=combined.authors)

        if len(languages) > 1:
            warn(f"found multiple languages for {submission.name}, using {combined.language}")
        if len(entrypoints) > 1:
            warn(f"found multiple languages for {submission.name}, using {combined.entrypoint}")
        if len(authors) > 1:
            names = ", ".join([a.name for a in combined.authors])
            warn(f"found multiple languages for {submission.name}, using {names}")

        if not found_match:
            warn(f"{submission.name} not covered by submissions.yaml")

        self._combined[submission.path] = combined
        return combined
