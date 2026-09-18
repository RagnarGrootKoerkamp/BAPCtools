from pathlib import Path

from bapctools import verdicts


class MockTestCase:
    def __init__(self, short_path):
        self.short_path = short_path
        self.name = short_path.as_posix()


class MockRun:
    def __init__(self, test_case, result=None):
        self.test_case = test_case
        self.skip = False
        self.result = result


class MockResult:
    def __init__(self, verdict, duration, timeout):
        self.duration = duration
        self.timeout_expired = duration >= timeout
        self.verdict = verdict


def make_run(short_path, verdict=None, duration=None, timeout=None):
    assert (verdict is None) == (duration is None)
    assert (verdict is None) == (timeout is None)
    if verdict is None:
        return MockRun(MockTestCase(short_path))
    else:
        return MockRun(MockTestCase(short_path), MockResult(verdict, duration, timeout))


AC = verdicts.Verdict.ACCEPTED
WA = verdicts.Verdict.WRONG_ANSWER
TLE = verdicts.Verdict.TIME_LIMIT_EXCEEDED
RTE = verdicts.Verdict.RUNTIME_ERROR


def test_inherited_inference():
    runs = [
        make_run(Path("sample/1"), AC, 0.5, 1),
        make_run(Path("sample/2"), AC, 0.5, 1),
        make_run(Path("secret/a/1"), AC, 0.5, 1),
        make_run(Path("secret/a/2"), AC, 0.5, 1),
        make_run(Path("secret/a/3"), AC, 0.5, 1),
        make_run(Path("secret/b/1"), AC, 0.5, 1),
        make_run(Path("secret/c"), AC, 0.5, 1),
    ]
    verds = verdicts.Verdicts(runs)
    verds.update(runs[2])  # secret/a/1
    verds.update(runs[3])  # secret/a/2
    verds.update(runs[4])  # secret/a/3
    verds.update(runs[6])  # secret/c
    verds.update(runs[5])  # secret/b/1
    verds.update(runs[0])  # sample/1
    assert verds[Path()] is None
    verds.update(runs[1])  # sample/2
    assert verds[Path()] == AC


def test_first_error():
    runs = [
        make_run(Path("sample/1"), AC, 0.5, 1),
        make_run(Path("sample/2"), AC, 0.5, 1),
        make_run(Path("secret/a/1"), AC, 0.5, 1),
        make_run(Path("secret/a/2"), WA, 0.5, 1),
        make_run(Path("secret/a/3"), WA, 0.5, 1),
        make_run(Path("secret/b/1")),
        make_run(Path("secret/c")),
    ]
    verds = verdicts.Verdicts(runs)
    assert all(verds.run_is_needed(run) for run in runs)
    verds.update(runs[2])  # secret/a/1
    verds.update(runs[4])  # secret/a/3
    assert verds[Path("secret/a")] is None
    assert verds.run_is_needed(runs[3])  # secret/a/2
    verds.update(runs[3])  # secret/a/2
    assert verds[Path("secret/a")] == WA
    assert verds[Path("secret")] == WA
    assert verds[Path()] is None
    verds.update(runs[0])  # sample/1
    verds.update(runs[1])  # sample/2
    assert verds[Path()] == WA


def test_efficiency():
    # Setting a verdict takes linear time: it checks the verdicts of all siblings to determine the parent's verdict.
    # This means that this test_efficiency() runs in quadratic time.
    size = 1000
    runs = [make_run(Path(f"a/{i}"), AC, 0.5, 1) for i in range(size)]
    verds = verdicts.Verdicts(runs)
    evens = range(0, size, 2)
    odds = range(1, size, 2)
    for i in reversed(evens):
        verds.update(runs[i])
    for i in odds:
        verds.update(runs[i])
    assert verds[Path()] == AC


def test_parent_overwrite():
    # If implemented badly, will overwrite verdict at `secret/a' (and crash)
    runs = [
        make_run(Path("sample/1")),
        make_run(Path("sample/2")),
        make_run(Path("secret/a/1"), WA, 0.5, 1),
        make_run(Path("secret/a/2"), WA, 0.5, 1),
        make_run(Path("secret/a/3"), RTE, 0.5, 1),
        make_run(Path("secret/b/1")),
        make_run(Path("secret/c")),
    ]
    verds = verdicts.Verdicts(runs, 1)
    verds.update(runs[2])
    assert verds[Path("secret/a")] == WA
    verds.update(runs[3])  # should not try to write 'secret/a' again
    assert verds[Path("secret/a")] == WA
    verds.update(runs[4])  # should not try to write 'secret/a' again
    assert verds[Path("secret/a")] == WA


def test_slowest_test_case():
    runs = [
        make_run(Path("sample/1"), AC, 0.5, 3),
        make_run(Path("sample/2"), AC, 0.5, 3),
        make_run(Path("secret/a/1"), TLE, 2.9, 3),
        make_run(Path("secret/a/2"), RTE, 3.5, 3),
        make_run(Path("secret/a/3"), TLE, 3.2, 3),
        make_run(Path("secret/b/1")),
        make_run(Path("secret/c")),
    ]
    verds = verdicts.Verdicts(runs, verdicts.RunUntil.DURATION)
    for i in range(5):
        verds.update(runs[i])
    assert verds.salient_test_case() == (Path("secret/a/1"), 2.9)
    assert verds.slowest_test_case() == (Path("secret/a/2"), 3.5)
