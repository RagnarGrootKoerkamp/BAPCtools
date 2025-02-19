import pytest
import yaml
from pathlib import Path
from typing import cast, Any
from unittest.mock import call, MagicMock

import config
import problem

RUN_DIR = Path.cwd().resolve()

config.args.verbose = 2
config.args.error = True
config.set_default_args()


# return list of {yaml: {...}, ...} documents
def read_tests(yaml_name) -> list[dict]:
    docs = [
        test
        if "uuid" in test["yaml"]
        else {**test, "yaml": {**test["yaml"], "uuid": "00000000-0000-0000-0000-000000000000"}}
        for test in yaml.load_all(
            (RUN_DIR / f"test/yaml/problem/{yaml_name}.yaml").read_text(),
            Loader=yaml.SafeLoader,
        )
    ]
    assert isinstance(docs, list) and all(isinstance(doc, dict) for doc in docs), docs
    return docs


def assert_equal(obj: Any, expected: Any):
    if isinstance(expected, list):
        assert isinstance(obj, list), "Expected a list"
        for a, b in zip(obj, expected):
            assert_equal(a, b)
        return

    if isinstance(expected, dict):
        for key, value in expected.items():
            if hasattr(obj, key):
                assert_equal(getattr(obj, key), value)
            elif isinstance(obj, dict) and key in obj:
                assert_equal(obj[key], value)
            else:
                assert False, f"Not supporting {obj}.{key} == {value}"

    if not isinstance(expected, dict):
        assert obj == expected


class MockProblem:
    path = Path("test/problems/hello")


class TestProblemYaml:
    @pytest.mark.parametrize("testdata", read_tests("valid"))
    def test_valid(self, testdata):
        config.n_error = 0
        config.n_warn = 0

        p = problem.ProblemSettings(testdata["yaml"], cast(problem.Problem, MockProblem()))
        assert config.n_error == 0 and config.n_warn == 0, (
            f"Expected zero errors and warnings, got {config.n_error} and {config.n_warn}"
        )
        if "eq" in testdata:
            assert_equal(p, testdata["eq"])

    @pytest.mark.parametrize("testdata", read_tests("invalid"))
    def test_invalid(self, monkeypatch, testdata):
        config.n_error = 0
        config.n_warn = 0

        fatal = MagicMock(name="fatal", side_effect=SystemExit(-42))
        error = MagicMock(name="error")
        warn = MagicMock(name="warn")
        for module in ["problem", "util"]:
            monkeypatch.setattr(f"{module}.fatal", fatal)
            monkeypatch.setattr(f"{module}.error", error)
            monkeypatch.setattr(f"{module}.warn", warn)

        # Still expecting no change, because we're mocking the functions that increment these values
        assert config.n_error == 0 and config.n_warn == 0, (
            f"Expected zero errors and warnings, got {config.n_error} and {config.n_warn}"
        )

        try:
            problem.ProblemSettings(testdata["yaml"], cast(problem.Problem, MockProblem()))
        except SystemExit as e:
            assert e.code == -42

        assert ([call(testdata["fatal"])] if "fatal" in testdata else []) == fatal.mock_calls

        if isinstance(testdata.get("error", None), str):
            testdata["error"] = [testdata["error"]]
        assert [call(x) for x in testdata.get("error", [])] == error.mock_calls

        if isinstance(testdata.get("warn", None), str):
            testdata["warn"] = [testdata["warn"]]
        assert [call(x) for x in testdata.get("warn", [])] == warn.mock_calls
