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
permitted: {'sample': {'AC'}}, required: {}

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


def shortform(verdict):
    """Transform verbose forms like ACCEPTED to short like AC, if needed."""
    for long, short in [
        ("ACCEPTED", "AC"),
        ("WRONG_ANSWER", "WA"),
        ("TIME_LIMIT_EXCEEDED", "TLE"),
        ("RUN_TIME_ERROR", "RTE"),
    ]:
        if verdict == long:
            verdict = short
    return verdict


class Expectations:
    """The expectations for a submission matching a submission pattern.

    >>> e = Expectations("wrong answer")
    >>> e._required_verdicts
    {'': {'WA'}}
    >>> e._permitted_verdicts == {'': {'AC', 'WA'}}
    True
    >>> e.is_permitted_verdict("AC", "sample/1")
    True
    >>> e.is_permitted_verdict("RTE", "sample/1")
    False
    >>> unexpected_results = {"sample/1": "AC", "secret/1": "AC", "secret/2": "AC"}
    >>> expected_results = {"sample/1": "AC", "secret/1": "AC", "secret/2": "WA"}
    >>> missing = e.missing_required_verdicts(unexpected_results)
    >>> missing['']
    {'WA'}
    >>> missing = e.missing_required_verdicts(expected_results)
    >>> missing
    {}
    >>> (e.is_satisfied_by(expected_results), e.is_satisfied_by(unexpected_results))
    (True, False)

    Specify expectations by testgroup:

    >>> f = Expectations({'sample': 'accepted', 'secret': 'wrong answer'})
    >>> f._permitted_verdicts == {'sample': {'AC'}, 'secret': {'AC', 'WA'}}
    True
    >>> f._required_verdicts['secret']
    {'WA'}
    """

    def __init__(self, expectations: str | list[int | float] | dict):
        """
        Arguments
        ---------

        expectations
            list of common expectations, or range, or map
        """

        self._permitted_verdicts: dict[str, set[str]] = dict()
        self._required_verdicts: dict[str, set[str]] = dict()

        def set_common(pattern, abbreviation):
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
                self._permitted_verdicts[pattern] = permissions
            if requirements is not None:
                self._required_verdicts[pattern] = requirements

        def parse_expectations(pattern, expectations):
            if isinstance(expectations, str):
                set_common(pattern, expectations)
            elif isinstance(expectations, list):
                pass  # NOT IMPLEMENTED
            elif isinstance(expectations, dict):
                for k, val in expectations.items():
                    if k.startswith("sample") or k.startswith("secret"):
                        if pattern != "":
                            assert False  # only permitted on top level!
                        parse_expectations(k, val)
                    elif k == "permitted":
                        self._permitted_verdicts[pattern] = (
                            val if isinstance(val, set) else set(val)
                        )
                    elif k == "required":
                        self._required_verdicts[pattern] = val if isinstance(val, set) else set(val)
                    elif k in ["judge_message", "score", "fractional_score"]:
                        pass  # NOT IMPLEMENTED
                    else:
                        assert False  # unrecognised key

        parse_expectations("", expectations)

    def permissions_for_testcase(self, path) -> dict[str, set[str]]:
        """Returns a dictionary over the patterns that apply for the given test case path.

        >>> e = Expectations( {'secret': { 'permitted': ['AC', 'TLE', 'WA']},
        ...                    'secret/(tc)?[0-9]+-huge': { 'permitted': ['TLE'] },
        ...                    'secret/[0-9]+-disconnected': { 'permitted': ['WA'] }})
        >>> p = e.permissions_for_testcase("secret/tc05-huge")
        >>> p == { 'secret': {'TLE', 'WA', 'AC'}, 'secret/(tc)?[0-9]+-huge': {'TLE'}}
        True
        >>> p = e.permissions_for_testcase("secret/05-disconnected")
        >>> p == {'secret': {'TLE', 'WA', 'AC'}, 'secret/[0-9]+-disconnected': {'WA'}}
        True
        >>> p = e.permissions_for_testcase("secret/abc-disconnected")
        >>> p ==  {'secret': {'TLE', 'WA', 'AC'}}
        True
        """

        return {
            pattern: verdicts
            for pattern, verdicts in self._permitted_verdicts.items()
            if re.match(pattern, path)
        }

    def permitted_verdicts_for_testcase(self, path) -> set[str]:
        """Returns a set of verdicts that is permitted at the given test case path.

        Permissions are restrictions, so that if several permissions apply,
        their *intersection* is permitted

         >>> e = Expectations( {'secret': { 'permitted': ['AC', 'TLE']},
         ...                    'secret/foo': { 'permitted': ['RTE', 'TLE'] }})
         >>> e.permitted_verdicts_for_testcase("secret/foo")
         {'TLE'}
        """
        permitted_verdicts = set(["AC", "TLE", "WA", "RTE"])
        for verdicts in self.permissions_for_testcase(path).values():
            permitted_verdicts &= verdicts
        return permitted_verdicts

    def is_permitted_verdict(self, verdict: str, path):
        """Is the result permitted for the testcase at the given path?

        Accepts verdicts in long form. (Maybe it shouldn't.)
        """
        return shortform(verdict) in self.permitted_verdicts_for_testcase(path)

    def missing_required_verdicts(
        self, verdict_for_testcase: dict[str, str]
    ) -> dict[str, set[str]]:
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
        for pattern, required_verdicts in self._required_verdicts.items():
            for testcase, verdict in verdict_for_testcase.items():
                verdict = shortform(verdict)
                if re.match(pattern, testcase) and verdict in required_verdicts:
                    break
            else:
                missing[pattern] = required_verdicts
        return missing

    def is_satisfied_by(self, results: dict[str, str]) -> bool:
        """Are all requirements satisfied?"""
        missing = self.missing_required_verdicts(results)
        return all(self.is_permitted_verdict(results[path], path) for path in results) and all(
            not missing_verdict for missing_verdict in missing.values()
        )

    def __repr__(self):
        return f"permitted: {self._permitted_verdicts}, required: {self._required_verdicts}"


class Registry(dict):
    """A dictionary-like class that maps patterns to expectations."""

    @staticmethod
    def from_dict(dictionary):
        """Factory method."""
        return Registry({k: Expectations(v) for k, v in dictionary.items()})

    def for_path(self, path: Path):
        """Return a dictionary mapping patterns to Expectations.

        Parameters:

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

    def check(self, results) -> bool:
        """Do the results satisfy all the expectations?"""
        return all(e.is_satisfied_by(results) for e in self.values())


if __name__ == "__main__":
    import doctest

    doctest.testmod()
