import verdicts
from pathlib import Path

AC = verdicts.Verdict.ACCEPTED
WA = verdicts.Verdict.WRONG_ANSWER
PATHS = ["sample/1", "sample/2", "secret/a/1", "secret/a/2", "secret/a/3", "secret/b/1"]


class TestVerdicts:
    def test_inherited_inference(self):
        verds = verdicts.Verdicts(Path(p) for p in PATHS)
        assert len(verds.testgroups) == 5
        assert Path("secret/a/1") == verds.set(Path("secret/a/1"), AC)
        assert Path("secret/a/2") == verds.set(Path("secret/a/2"), AC)
        assert Path("secret/a") == verds.set(Path("secret/a/3"), AC)
        assert Path("secret") == verds.set(Path("secret/b/1"), AC)
        assert Path("sample/1") == verds.set(Path("sample/1"), AC)
        assert verds.verdicts[Path(".")] is None
        assert Path(".") == verds.set(Path("sample/2"), AC)

    def test_first_error(self):
        verds = verdicts.Verdicts(Path(p) for p in PATHS)
        assert len(verds.testgroups) == 5
        assert Path("secret/a/1") == verds.set(Path("secret/a/1"), AC)
        assert Path("secret/a/3") == verds.set(Path("secret/a/3"), WA)
        assert verds.verdicts[Path("secret/a")] is None
        assert Path("secret") == verds.set(Path("secret/a/2"), WA)
        assert verds.verdicts[Path("secret/a")] == WA
        assert verds.verdicts[Path("secret")] == WA
        assert verds.verdicts[Path(".")] is None
        verds.set(Path("sample/1"), AC)
        verds.set(Path("sample/2"), AC)
        assert verds.verdicts[Path(".")] == WA
