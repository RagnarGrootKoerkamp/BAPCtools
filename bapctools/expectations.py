from collections.abc import Mapping, Sequence
from typing import Final, Optional

from bapctools.util import YamlParser
from bapctools.verdicts import Verdict

VERDICTS: Final[Sequence[Verdict]] = [
    Verdict.ACCEPTED,
    Verdict.WRONG_ANSWER,
    Verdict.TIME_LIMIT_EXCEEDED,
    Verdict.RUNTIME_ERROR,
]
KNOWN_VERDICTS: Final[Mapping[str, Verdict]] = {v.short(): v for v in VERDICTS}


class Expectation:
    def __init__(self, key: str, parser: YamlParser, test_case_glob: Optional[str] = None):
        self.test_case_glob: Optional[str] = test_case_glob

        def extract_verdicts(key: str) -> set[Verdict]:
            verdicts = parser.extract_optional_list(key, str)
            if not verdicts:
                return set(VERDICTS)
            if any(v not in KNOWN_VERDICTS for v in verdicts):
                parser.bar.warn(
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
                parser.bar.warn(
                    f"(`{parser.parent_path}.score` must be a single float or a list of two floats.)"
                )
            parser.bar.warn("Scoring is not implemented in BAPCtools.")

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
                parser.bar.warn(
                    f"`{parser.parent_path}.use_for_time_limit` must be bool or `lower` or `upper`. SKIPPED."
                )


# class Expectations:
#    def __init__(self, submission_glob: str, yaml_data: dict[object, object]) -> None:
#        self.submission_glob: str = submission_glob
#        self.language: str
#        self.entrypoint: str
#        self.authors: list[Person]
#        self.model_solution: bool = False
#
#        self.expectations = list[Expectation]
