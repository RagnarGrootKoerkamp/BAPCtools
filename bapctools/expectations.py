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


def _match(glob: str, path: Path) -> bool:
    # TODO: implement this properly
    # TODO: handle stuff like a.{cpp,py}
    if not glob.startswith("/"):
        glob = "/" + glob
    if not glob.endswith("/"):
        glob = glob + "/"
    glob_parts = glob.split("/")[1:-1]
    path_parts = path.parts
    if len(glob_parts) > len(path_parts):
        return False
    for glob_part, path_part in zip(glob_parts, path_parts):
        glob_part = re.escape(glob_part).replace(re.escape("*"), ".*")
        if not re.fullmatch(glob_part, path_part):
            return False
    return True


VERDICTS: Final[Sequence[Verdict]] = [
    Verdict.ACCEPTED,
    Verdict.WRONG_ANSWER,
    Verdict.TIME_LIMIT_EXCEEDED,
    Verdict.RUNTIME_ERROR,
]
KNOWN_VERDICTS: Final[Mapping[str, Verdict]] = {v.short(): v for v in VERDICTS}


class TestcaseExpectation:
    def __init__(self, parser: YamlParser, test_case_glob: Optional[str] = None):
        self.test_case_glob: Optional[str] = test_case_glob

        def extract_verdicts(key: str) -> set[Verdict]:
            verdicts = parser.extract_optional_list(key, str)
            if not verdicts:
                return set(VERDICTS)
            if any(v not in KNOWN_VERDICTS for v in verdicts):
                warn(
                    f"some values for key `{parser.parent_path}.{key}` in {parser.source} are unknown. SKIPPED."
                )
                return set(VERDICTS)
            return {KNOWN_VERDICTS[v] for v in verdicts}

        self.permitted: set[Verdict] = extract_verdicts("permitted")
        self.required: set[Verdict] = extract_verdicts("required")

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
        self.upper_time_limit: bool = Verdict.TIME_LIMIT_EXCEEDED in self.required
        use_for_time_limit = parser.pop("use_for_time_limit")
        if use_for_time_limit is not None:
            if use_for_time_limit in [False, "upper"]:
                self.lower_time_limit = False
            if use_for_time_limit in [False, "lower"]:
                self.upper_time_limit = False
            if use_for_time_limit not in [True, False, "lower", "upper"]:
                warn(
                    f"`{parser.parent_path}.use_for_time_limit` must be bool or `lower` or `upper`. SKIPPED."
                )

    def matches(self, testcase: Testcase) -> bool:
        if self.test_case_glob is None:
            return True
        return _match(self.test_case_glob, testcase.short_path)


class SubmissionExpectation:
    def __init__(self, submission_glob: str, yaml_data: dict[object, object]) -> None:
        self.submission_glob: str = submission_glob

        parser = YamlParser("submissions.yaml", yaml_data, submission_glob)

        self.language: Optional[str] = parser.extract_optional("language", str)
        self.entrypoint: Optional[str] = parser.extract_optional("entrypoint", str)
        self.authors: list[Person] = Person.extract_optional_persons(parser, "authors")
        self.model_solution: bool = parser.extract("model_solution", False)

        self.expectations: list[TestcaseExpectation] = [TestcaseExpectation(parser)]
        for key in list(parser.yaml):
            if not isinstance(key, str):
                continue
            if not key.startswith("sample") and key.startswith("secret"):
                continue
            self.expectations.append(TestcaseExpectation(parser, key))
        parser.check_unknown_keys()

    def matches(self, submission: "Submission") -> bool:
        return _match(self.submission_glob, submission.short_path)

    def all_matches(self, testcase: Testcase) -> list[TestcaseExpectation]:
        # TODO: warn if if there is no match?
        return [e for e in self.expectations if e.matches(testcase)]

    def all_permitted(self, testcase: Testcase) -> set[Verdict]:
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
        if submission.short_path in self._combined:
            return self._combined[submission.short_path]

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

        self._combined[submission.short_path] = combined
        return combined
