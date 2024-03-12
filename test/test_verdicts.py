import verdicts

AC = verdicts.Verdict.ACCEPTED
WA = verdicts.Verdict.WRONG_ANSWER
PATHS = ["sample/1", "sample/2", "secret/a/1", "secret/a/2", "secret/a/3", "secret/b/1"]


class TestVerdicts:
    def test_inherited_inference(self):
        verds = verdicts.Verdicts(PATHS)
        assert len(verds.testgroups) == 5
        assert verds.set("secret/a/1", AC)  == "secret/a/1"
        assert verds.set("secret/a/2", AC)  == "secret/a/2"
        assert verds.set("secret/a/3", AC)  == "secret/a"
        assert verds.set("secret/b/1", AC)  == "secret"
        assert verds.set("sample/1", AC)  == "sample/1"
        assert verds.verdicts["."] is None
        assert verds.set("sample/2", AC) == '.'

    def test_first_error(self):
        verds = verdicts.Verdicts(PATHS)
        assert len(verds.testgroups) == 5
        assert verds.set("secret/a/1", AC) == "secret/a/1"
        assert verds.set("secret/a/3", WA) == "secret/a/3"
        assert verds.verdicts["secret/a"] is None
        assert verds.set("secret/a/2", WA) == "secret"
        assert verds.verdicts["secret/a"] == WA
        assert verds.verdicts["secret"] == WA
        assert verds.verdicts["."] is None
        verds.set("sample/1", AC)
        verds.set("sample/2", AC)
        assert verds.verdicts["."] == WA
