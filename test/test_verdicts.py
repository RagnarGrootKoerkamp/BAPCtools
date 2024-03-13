import verdicts

AC = verdicts.Verdict.ACCEPTED
WA = verdicts.Verdict.WRONG_ANSWER
PATHS = ["sample/1", "sample/2", "secret/a/1", "secret/a/2", "secret/a/3", "secret/b/1", "secret/c"]


class TestVerdicts:
    def test_inherited_inference(self):
        verds = verdicts.Verdicts(PATHS)
        assert verds.set("secret/a/1", AC) == "secret/a/1"
        assert verds.set("secret/a/2", AC) == "secret/a/2"
        assert verds.set("secret/a/3", AC) == "secret/a"
        assert verds.set("secret/c", AC) == "secret/c"
        assert verds.set("secret/b/1", AC) == "secret"
        assert verds.set("sample/1", AC) == "sample/1"
        assert verds.verdict["."] is None
        assert verds.set("sample/2", AC) == '.'

    def test_first_error(self):
        verds = verdicts.Verdicts(PATHS)
        assert verds.num_unknowns["secret/a"] == 3
        assert verds.set("secret/a/1", AC) == "secret/a/1"
        assert verds.set("secret/a/3", WA) == "secret/a/3"
        assert verds.verdict["secret/a"] is None
        assert verds.first_unknown["secret/a"] == "secret/a/2"
        assert verds.num_unknowns["secret/a"] == 1
        assert verds.set("secret/a/2", WA) == "secret"
        assert verds.verdict["secret/a"] == WA
        assert verds.verdict["secret"] == WA
        assert verds.verdict["."] is None
        verds.set("sample/1", AC)
        verds.set("sample/2", AC)
        assert verds.verdict["."] == WA

    def test_efficiency(self):
        # If done badly, this takes quadratic time
        size = 100000
        many_paths = [f"a/{i}" for i in range(size)]
        verds = verdicts.Verdicts(many_paths)
        evens = range(0, size, 2)
        odds = range(1, size, 2)
        for i in reversed(evens):
            verds.set(f"a/{i}", AC)
        for i in odds:
            verds.set(f"a/{i}", AC)

    def test_parent_overwrite(self):
        # If implmented badly, will overwrite verdict at `secret/a' (and crash)
        verds = verdicts.Verdicts(PATHS)
        verds.set("secret/a/1", WA)
        assert verds.verdict['secret/a'] == WA
        verds.set("secret/a/2", WA)  # should not try to write 'sexret/a' again

