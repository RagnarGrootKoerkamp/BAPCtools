import verdicts

class MockTestcase:
    def __init__(self, name):
        self.name = name

AC = verdicts.Verdict.ACCEPTED
WA = verdicts.Verdict.WRONG_ANSWER
PATHS = [MockTestcase(p) for p in ["sample/1", "sample/2", "secret/a/1", "secret/a/2", "secret/a/3", "secret/b/1", "secret/c"]]


class TestVerdicts:
    def test_inherited_inference(self):
        verds = verdicts.Verdicts(PATHS, 1.0)
        verds.set("secret/a/1", AC, 0.5)
        verds.set("secret/a/2", AC, 0.5)
        verds.set("secret/a/3", AC, 0.5)
        verds.set("secret/c", AC, 0.5)
        verds.set("secret/b/1", AC, 0.5)
        verds.set("sample/1", AC, 0.5)
        assert verds["."] is None
        verds.set("sample/2", AC, 0.5)
        assert verds["."] == AC

    def test_first_error(self):
        verds = verdicts.Verdicts(PATHS, 1.0)
        assert all(verds.run_is_needed(f"secret/a/{i}") for i in range(1, 3))
        verds.set("secret/a/1", AC, 0.5)
        verds.set("secret/a/3", WA, 0.5)
        assert verds["secret/a"] is None
        assert verds.run_is_needed("secret/a/2")
        verds.set("secret/a/2", WA, 0.5)
        assert verds["secret/a"] == WA
        assert verds["secret"] == WA
        assert verds["."] is None
        verds.set("sample/1", AC, 0.5)
        verds.set("sample/2", AC, 0.5)
        assert verds["."] == WA

    def test_efficiency(self):
        # Setting a verdict takes linear time: it checks the verdicts of all siblings to determine the parent's verdict.
        # This means that this test_efficiency() runs in quadratic time.
        size = 1000
        many_paths = [MockTestcase(f"a/{i}") for i in range(size)]
        verds = verdicts.Verdicts(many_paths, 1.0)
        evens = range(0, size, 2)
        odds = range(1, size, 2)
        for i in reversed(evens):
            verds.set(f"a/{i}", AC, 0.5)
        for i in odds:
            verds.set(f"a/{i}", AC, 0.5)

    def test_parent_overwrite(self):
        # If implemented badly, will overwrite verdict at `secret/a' (and crash)
        verds = verdicts.Verdicts(PATHS, 1.0)
        verds.set("secret/a/1", WA, 0.5)
        assert verds["secret/a"] == WA
        verds.set("secret/a/2", WA, 0.5)  # should not try to write 'secret/a' again

    def test_slowest_testcase(self):
        verds = verdicts.Verdicts(PATHS, 3, verdicts.RunUntil.DURATION)
        verds.set("sample/1", AC, 0.5)
        verds.set("sample/2", AC, 0.5)
        verds.set("secret/a/1", "TLE", 2.9)
        verds.set("secret/a/2", "RTE", 3.5)
        verds.set("secret/a/3", "TLE", 3.2)
        assert verds.salient_testcase() == ("secret/a/1", 2.9)
        assert verds.slowest_testcase() == ("secret/a/2", 3.5)
