"""Expectations for a submission

Here is a sample expectations.yaml file:

    accepted/: accepted     # Every submission in accepted/* should be accepted
    wrong_answer/th.py:     # This particular submission ...
      sample: accepted      # ... should be acceped on sample
      secret: wrong answer  # ... but fail with WA on some test case in secret
    mixed/failing.java      # For this particular submission, ...
      secret/huge/graph07:  # ... on this particular test case ...
        permitted: [TLE, RTE] # ... only TLE and RTE are permitted

A yaml parser will turn this into a dict that can be fed to the Registry class:

>>> exp_dict = {
...     "accepted/": "accepted",
...     "wrong_answer/th.py": {"sample": "accepted", "secret": "wrong answer"},
...     "mixed/failing.java": {"secret/huge/graph07": {"permitted": ["TLE", "RTE"]}},
...     "mixed/": {"sample": "accepted"}
... }


>>> registry = Registry.from_dict(exp_dict)
>>> registry['mixed/']
'sample': {permitted: {'AC'}, required: None}

Expectations for a single submission can now be extracted from
the registry. Here, the submission `mixed/failing.java` matches two patterns,
so those will be the expectations that apply to that submission.

>>> sub_registry = registry.for_path(Path("mixed/failing.java"))
>>> sorted(sub_registry.keys())
['mixed/', 'mixed/failing.java']

Expectations for a submission can be compared with actual validation
results. This runs all (in this case, both), sets of expecations
against the results.

>>> results_ac = { "sample/1": "AC", "secret/1": "AC", "secret/2": "AC" }
>>> results_wa = { "sample/1": "WA", "secret/1": "AC", "secret/2": "WA" }
>>> sub_registry.check(results_ac)
True
>>> sub_registry.check(results_wa)
False


Altenatively, supply a submission path check the submission and results
directly against the expectations dictionary.

>>> registry.for_path(Path("accepted/ragnar.cpp")).check(results_ac)
True
>>> registry.for_path(Path("accepted/ragnar.cpp")).check(results_wa)
False
>>> registry.for_path(Path("wrong_answer/th.py")).check(results_wa)
False
>>> results_wa_secret = { "sample/1": "AC", "secret/1": "AC", "secret/2": "WA" }
>>> registry.for_path(Path("wrong_answer/th.py")).check(results_wa_secret)
True

Checking some results against no relevant expectations always succeeds:
>>> registry.for_path(Path("mixed/failing.java")).check(results_wa_secret)
True

Terminology
-----------

verdict
    A testcase can have a verdict, which is any of 'AC', 'WA', 'RTE', 'TLE'.
    (Note that the verdict 'JE' is never expected.)

result
    a verdict for a path representing a testcase, like "TLE" for "secret/huge/random-01"

score
    A finite number, often just an integer in the range {0, ..., 100}, but can be a float.
    NOT IMPLEMENTED

range
    A string of two space-separated numbers, like '0 30' or '-inf 43' or '3.14 3.14';
    a one-value range can be abbreviated: '5' is the range '5 5'.
    NOT IMPLEMENTED
"""

from pathlib import Path
import re


class TestCasePattern(str):
    """A pattern that matches against testgroups and -cases."""

    def __new__(cls, content):
        if content != "" and not content.startswith("sample") and not content.startswith("secret"):
            raise ValueError(f"Unexpected test case pattern {content}")
        return super().__new__(cls, content)


class BaseExpectations:
    """Base expectations."""

    def __init__(self, expectations: str | list[int | float]):
        self._permitted_verdicts: set[str] | None = None
        self._required_verdicts: set[str] | None = None

        if isinstance(expectations, str):
            self._set_common(expectations)
        elif isinstance(expectations, list):
            raise ValueError("Range expecations not implemented")
        elif isinstance(expectations, dict):
            for k, val in expectations.items():
                if k == "permitted":
                    self._permitted_verdicts = val if isinstance(val, set) else set(val)
                elif k == "required":
                    self._required_verdicts = val if isinstance(val, set) else set(val)
                elif k in ["judge_message", "score", "fractional_score"]:
                    raise ValueError(f"Key {k} not implemented")
                else:
                    raise ValueError(f"Unrecognised key {k}")

    def permitted_verdicts(self) -> set[str]:
        """Returns a set of verdicts."""
        return self._permitted_verdicts or set(["AC", "WA", "TLE", "RTE"])

    def required_verdicts(self) -> set[str]:
        """Returns a set of verdicts."""
        return self._required_verdicts or set()

    def _set_common(self, abbreviation):
        permissions = None
        requirements = None
        if abbreviation == "accepted":
            permissions = set(["AC"])
        elif abbreviation == "wrong answer":
            permissions = set(["AC", "WA"])
            requirements = set(["WA"])
        elif abbreviation == "time limit exceeded":
            permissions = set(["AC", "TLE"])
            requirements = set(["TLE"])
        elif abbreviation == "runtime exception":
            permissions = set(["AC", "RTE"])
            requirements = set(["RTE"])
        elif abbreviation == "does not terminate":
            permissions = set(["AC", "RTE", "TLE"])
            requirements = set(["RTE", "TLE"])
        elif abbreviation == "not accepted":
            requirements = set(["RTE", "TLE", "WA"])
        else:
            assert False, f"unknown abbreviation {abbreviation}"
        if permissions is not None:
            self._permitted_verdicts = permissions
        if requirements is not None:
            self._required_verdicts = requirements

    def __repr__(self):
        return f"permitted: {self._permitted_verdicts}, required: {self._required_verdicts}"


class Expectations(dict[TestCasePattern, BaseExpectations]):
    """The expectations for a submission pattern; it maps testcase patterns
    to BaseExpectations.

    >>> e = Expectations("accepted")
    >>> e
    '': {permitted: {'AC'}, required: None}
    >>> e.permitted_verdicts_for_testcase(Path("sample/1"))
    {'AC'}

    Specify expectations by testgroup:

    >>> f = Expectations({'': 'wrong answer', 'sample': 'accepted', 'secret': 'wrong answer'})
    >>> f['sample']
    permitted: {'AC'}, required: None

    Or by testcase
    >>> list(sorted(f.expectations_for_testcase('sample/1').keys()))
    ['', 'sample']
    """

    def __init__(self, expectations: str | list[int | float] | dict):
        """
        Arguments
        ---------

        expectations
            list of common expectations, or range, or map
        """

        self.data: dict[str, BaseExpectations] = dict()

        if not isinstance(expectations, dict):
            expectations = {"": expectations}
        for k, val in expectations.items():
            if not (k == "" or k.startswith("sample") or k.startswith("secret")):
                raise ValueError(f"Unexpected test data pattern: {k}")
            self[TestCasePattern(k)] = BaseExpectations(val)

    def for_testcase(self, path: Path) -> dict[TestCasePattern, BaseExpectations]:
        """Returns a dictionary over the patterns that apply for the given test case path.

        >>> e = Expectations( {'secret': { 'permitted': ['AC', 'TLE', 'WA']},
        ...                    'secret/(tc)?[0-9]+-huge': { 'permitted': ['TLE'] },
        ...                    'secret/[0-9]+-disconnected': { 'permitted': ['WA'] }})
        >>> list(sorted(e.for_testcase("secret/tc05-huge").keys()))
        ['secret', 'secret/(tc)?[0-9]+-huge']
        >>> list(sorted(e.for_testcase("secret/05-disconnected").keys()))
        ['secret', 'secret/[0-9]+-disconnected']
        >>> list(sorted(e.for_testcase("secret/abc-disconnected").keys()))
        ['secret']
        """

        return {
            pattern: expectations
            for pattern, expectations in self.items()
            if re.match(pattern, str(path))
        }

    def permitted_verdicts_for_testcase(self, path: Path) -> set[str]:
        """Returns a set of verdicts that is permitted at the given test case path.

        Permissions are restrictions, so that if several permissions apply,
        their *intersection* is permitted

         >>> e = Expectations( {'secret': { 'permitted': ['AC', 'TLE']},
         ...                    'secret/foo': { 'permitted': ['RTE', 'TLE'] }})
         >>> e.permitted_verdicts_for_testcase("secret/foo")
         {'TLE'}
        """
        permitted_verdicts = set(["AC", "TLE", "WA", "RTE"])
        for exp in self.for_testcase(path).values():
            permitted_verdicts &= exp.permitted_verdicts()
        return permitted_verdicts

    def is_permitted(self, verdict: str, path: Path):
        """Is the result permitted for the testcase at the given path?

        Accepts verdicts in long form. (Maybe it shouldn't.)
        """
        return verdict in self.permitted_verdicts_for_testcase(path)

    def missing_required_verdicts(
        self, verdict_for_testcase: dict[Path, str]
    ) -> dict[TestCasePattern, set[str]]:
        """Which verdicts are missing?

        Returns a map of expectation patterns to sets of verdicts.

        >>> e = Expectations("does not terminate")
        >>> results = {"sample/1": "AC", "secret/1": "AC", "secret/2": "WA"}
        >>> e.missing_required_verdicts(results) ==  {'': {'RTE', 'TLE'}}
        True
        >>> results = {"sample/1": "AC", "secret/1": "TLE", "secret/2": "WA"}
        >>> e.missing_required_verdicts(results)
        {}
        """

        missing = dict()
        for tcpattern, exp in self.items():
            if not exp.required_verdicts():
                continue
            for testcase, verdict in verdict_for_testcase.items():
                if re.match(tcpattern, str(testcase)) and verdict in exp.required_verdicts():
                    break
            else:
                missing[tcpattern] = exp.required_verdicts()
        return missing

    def is_satisfied_by(self, results: dict[Path, str]) -> bool:
        """Are all requirements satisfied?"""
        missing = self.missing_required_verdicts(results)
        return all(self.is_permitted(results[path], path) for path in results) and all(
            not missing_verdict for missing_verdict in missing.values()
        )

    def __repr__(self):
        return ', '.join(f"'{k}': {{{repr(v)}}}" for k, v in self.items())


class Registry(dict[str, Expectations]):
    """A dictionary-like class that maps submission patterns to expectations."""

    @staticmethod
    def from_dict(dictionary):
        """Factory method."""
        return Registry({k: Expectations(v) for k, v in dictionary.items()})

    def for_path(self, path: Path):
        """Return a restricted Registry where all patterns
        match the given path.

        >>> registry = Registry({
        ...     'accepted': Expectations('accepted'),
        ...     'accepted/th': Expectations({'sample': 'accepted'}),
        ...     'wrong_answer': Expectations('wrong answer')
        ... })
        >>> for k, v in registry.for_path(Path('accepted/th.py')).items():
        ...    print(k, ":", v)
        accepted : '': {permitted: {'AC'}, required: None}
        accepted/th : 'sample': {permitted: {'AC'}, required: None}

        path:
            a pathlib.Path to a submission
        """
        return Registry(
            {
                pattern: expectation
                for pattern, expectation in self.items()
                if re.match(pattern, str(path))
            }
        )

    def is_permitted(self, verdict, testcase: Path) -> bool:
        """shut up"""

        return all(e.is_permitted(verdict, testcase) for e in self.values())

    def violated_permissions(
        self, verdict, testcase: Path
    ) -> list[tuple[str, TestCasePattern, set[str]]]:
        """Which permissions are violated by the given verdict for the given testcase?

        Return:
            A list of tuples; each tuple consists of
            - the submissions pattern
            - the test case pattern
            - the set of verdicts that was expected
            The list is sorted; in the typical case this means that less
            specific rules come first.
        """
        violations = []
        for prefix, expectation in self.items():
            for pattern, base in expectation.for_testcase(testcase).items():
                permitted_verdicts = base.permitted_verdicts()
                if verdict in permitted_verdicts:
                    continue
                violations.append((prefix, pattern, permitted_verdicts))
        return list(sorted(violations))

    def unsatisfied_requirements(
        self, verdict_for_testcase: dict[Path, str]
    ) -> list[tuple[str, TestCasePattern, set[str]]]:
        """Which permissions are violated by the given results?

        Paramters:
            verdict_for_testcase:
                a mapping of testcase path to verdict

        Return:
            A list of tuples; each tuple consists of
            - the submissions pattern
            - the test case pattern
            - the set of verdicts that was required
            The list is sorted; in the typical case this means that less
            specific rules come first.
        """
        missing = []
        for prefix, expectations in self.items():
            missing_verdicts = expectations.missing_required_verdicts(verdict_for_testcase)
            for pattern, verdicts in missing_verdicts.items():
                missing.append((prefix, pattern, verdicts))

        return missing

    def check(self, results) -> bool:
        """Do the results satisfy all the expectations?

        Note that expectations compose in different ways;
        permissions are subtractive, requirements additive.

        >>> registry = Registry(
        ...     a= Expectations({"sample": { 'permitted': ['AC', 'WA']}}),
        ...     b= Expectations({"sample": { 'permitted': ['AC', 'TLE']}})
        ... )
        >>> for v in ['AC', 'TLE', 'WA']:
        ...     result = {'sample': v }
        ...     print(f"{v}:", registry.check(result))
        AC: True
        TLE: False
        WA: False

        Typically, the expectations registered for a submission have
        patterns like `secret` and `secret/huge` rather than mutually
        exclusive `a` and `b`, and then this mechanism allows increasingly
        fine-grained specification.
        """
        return all(e.is_satisfied_by(results) for e in self.values())


if __name__ == "__main__":
    import doctest

    doctest.testmod()
