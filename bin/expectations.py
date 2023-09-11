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
...     "mixed/failing.java": {"secret/huge/graph07": {"permitted": ["TLE", "RTE"]}}
... }
>>> registry = Registry(exp_dict)

Expectations for a submission can now be extracted. Here, `accepted/ragnar.cpp`
is matched by the `accepted/` patterns, so those will be the expectations
for that submission.

>>> ragnar_expectations = registry.expectations("accepted/ragnar.cpp")

Compared with actual validation results:

>>> results_ac = { "sample/1": "AC", "secret/1": "AC", "secret/2": "AC" }
>>> results_wa = { "sample/1": "WA", "secret/1": "AC", "secret/2": "WA" }
>>> ragnar_expectations.is_satisfied_by(results_ac)
True

Altenatively, check the submission and results directly in the registry:

>>> registry.check_submission("accepted/ragnar.cpp", results_ac)
True
>>> registry.check_submission("accepted/ragnar.cpp", results_wa)
False
>>> registry.check_submission("wrong_answer/th.py", results_wa)
False
>>> results_wa_secret = { "sample/1": "AC", "secret/1": "AC", "secret/2": "WA" }
>>> registry.check_submission("wrong_answer/th.py", results_wa_secret)
True

Checking some results against no relevant expectations always succeeds:
>>> registry.check_submission("mixed/failing.java", results_wa_secret)
True
>>> registry.check_submission("mixed/failing.java", {"secret/huge/graph07": "WA" })
False
>>> registry.check_submission("mixed/failing.java", {"secret/huge/graph07": "TLE" })
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

from functools import lru_cache
import re


@staticmethod
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

@staticmethod
def matches(pattern, string):
    """ Return true if the string matches the pattern. This method *defines*
        what "matching" means.
    """
    #print(f"--{pattern}..{string}--", bool(re.match(pattern, string)))
    return re.match(pattern, string)



class Expectations:
    """The expectations for a submission.


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
            if abbreviation == "accepted":
                self._permitted_verdicts[pattern] = set(["AC"])
            elif abbreviation == "wrong answer":
                self._permitted_verdicts[pattern] = set(["AC", "WA"])
                self._required_verdicts[pattern] = set(["WA"])
            elif abbreviation == "time limit exceeded":
                self._permitted_verdicts[pattern] = set(["AC", "TLE"])
                self._required_verdicts[pattern] = set(["TLE"])
            elif abbreviation == "runtime exception":
                self._permitted_verdicts[pattern] = set(["AC", "RTE"])
                self._required_verdicts[pattern] = set(["RTE"])
            elif abbreviation == "does not terminate":
                self._permitted_verdicts[pattern] = set(["AC", "RTE", "TLE"])
                self._required_verdicts[pattern] = set(["RTE", "TLE"])
            elif abbreviation == "not accepted":
                self._required_verdicts[pattern] = set(["RTE", "TLE", "WA"])
            else:
                assert False, f"unknown abbreviation {abbreviation}"

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
                        self._permitted_verdicts[pattern] = val if isinstance(val, set) else set(val)
                    elif k == "required":
                        self._required_verdicts[pattern] = val if isinstance(val, set) else set(val)
                    elif k in ["judge_message", "score", "fractional_score"]:
                        pass  # NOT IMPLEMENTED
                    else:
                        assert False  # unrecognised key

        parse_expectations("", expectations)

    def permitted_verdicts_for_testcase(self, path) -> dict[str, str]:
        """Returns a dictionary over the patterns that apply for the given test case path.
        >>> e = Expectations( {'secret': { 'permitted': ['AC', 'TLE', 'WA']},
        ...                    'secret/[0-9]+-huge': { 'permitted': ['TLE'] },
        ...                    'secret/\d+-disconnected': { 'permitted': ['WA'] }})
        >>> e.permitted_verdicts_for_testcase("secret/05-huge") == { 'secret': {'TLE', 'WA', 'AC'}, 'secret/[0-9]+-huge': {'TLE'}}
        True
        >>> e.permitted_verdicts_for_testcase("secret/05-disconnected") ==  {'secret': {'TLE', 'WA', 'AC'}, 'secret/\\d+-disconnected': {'WA'}}
        True
        >>> e.permitted_verdicts_for_testcase("secret/abc-disconnected") ==  {'secret': {'TLE', 'WA', 'AC'}}
        True
        """
       # >>> e.permitted_verdicts_for_testcase("secret/015-connected")

        return {
            pattern: verdicts
            for pattern, verdicts in self._permitted_verdicts.items()
            if matches(pattern, path)
        }

    def is_permitted_verdict(self, verdict: str, path):
        """Is the result permitted for the testcase at the given path?"""
        verdict = shortform(verdict)
        for _, verdicts in self.permitted_verdicts_for_testcase(path).items():
            if verdict not in verdicts:
                return False
        return True

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
                if matches(pattern, testcase) and verdict in required_verdicts:
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

    def __str__(self):
        return f"permitted: {self._permitted_verdicts}\nrequired: {self._required_verdicts}"


class Registry:
    """Maps string that describe submissions to Expectation objects."""

    def __init__(self, registry):
        self.registry = {pat: Expectations(registry[pat]) for pat in registry}

    def __str__(self):
        return str(self.registry)

    @lru_cache
    def expectations(self, submission_path):
        """The expectations for a given submission.
        *Should* return the most specific match. (Currently assumes
        there's exactly one.)
        """
        expectations = None
        for pat, exp in self.registry.items():
            if matches(pat, submission_path):
                if expectations is not None:
                    assert False  # NOT IMPLEMENTED: every pattern can match at most once
                expectations = exp
        if expectations is None:
            assert False  # NOT IMPLEMENTED: every submission must match
        return expectations

    def check_submission(self, submission_path: str, results) -> bool:
        """Check that given results were expected for the submission at the given path."""
        expectations = self.expectations(submission_path)
        return expectations.is_satisfied_by(results)


if __name__ == "__main__":
    import doctest

    doctest.testmod()
