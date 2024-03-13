import verdicts

AC = verdicts.Verdict.ACCEPTED
WA = verdicts.Verdict.WRONG_ANSWER
PATHS = ["sample/1", "sample/2", "secret/a/1", "secret/a/2", "secret/a/3", "secret/b/1", "secret/c"]


class TestVerdicts:
    def test_inherited_inference(self):
        verds = verdicts.Verdicts(PATHS)
        verds["secret/a/1"] = AC
        verds["secret/a/2"] = AC
        verds["secret/a/3"] = AC
        verds["secret/c"] = AC
        verds["secret/b/1"] = AC
        verds["sample/1"] = AC
        assert verds["."] is None
        verds["sample/2"] = AC
        assert verds["."] == AC

    def test_first_error(self):
        verds = verdicts.Verdicts(PATHS)
        assert verds.num_unknowns["secret/a"] == 3
        verds["secret/a/1"] = AC
        verds["secret/a/3"] = WA
        assert verds["secret/a"] is None
        assert verds.first_unknown["secret/a"] == "secret/a/2"
        assert verds.num_unknowns["secret/a"] == 1
        verds["secret/a/2"] = WA
        assert verds["secret/a"] == WA
        assert verds["secret"] == WA
        assert verds["."] is None
        verds["sample/1"] = AC
        verds["sample/2"] = AC
        assert verds["."] == WA

    def test_efficiency(self):
        # If done badly, this takes quadratic time
        size = 100000
        many_paths = [f"a/{i}" for i in range(size)]
        verds = verdicts.Verdicts(many_paths)
        evens = range(0, size, 2)
        odds = range(1, size, 2)
        for i in reversed(evens):
            verds[f"a/{i}"] = AC
        for i in odds:
            verds[f"a/{i}"] = AC

    def test_parent_overwrite(self):
        # If implmented badly, will overwrite verdict at `secret/a' (and crash)
        verds = verdicts.Verdicts(PATHS)
        verds["secret/a/1"] = WA
        assert verds['secret/a'] == WA
        verds["secret/a/2"] = WA  # should not try to write 'sexret/a' again
