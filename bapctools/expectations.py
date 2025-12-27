import re
from collections.abc import Mapping, Sequence
from typing import Final, Optional

from bapctools.util import warn, YamlParser
from bapctools.verdicts import Verdict


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


class Expectation:
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


class Expectations:
    def __init__(self, submission_glob: str, yaml_data: dict[object, object]) -> None:
        self.submission_glob: str = submission_glob

        parser = YamlParser("submissions.yaml", yaml_data, submission_glob)

        self.language: Optional[str] = parser.extract_optional("language", str)
        self.entrypoint: Optional[str] = parser.extract_optional("entrypoint", str)
        self.authors: list[Person] = Person.extract_optional_persons(parser, "authors")
        self.model_solution: bool = parser.extract("model_solution", False)

        self.expectations: list[Expectation] = [Expectation(parser)]
        for key in list(parser.yaml):
            if not isinstance(key, str):
                continue
            if not key.startswith("sample") and key.startswith("secret"):
                continue
            self.expectations.append(Expectation(parser, key))
        parser.check_unknown_keys()
