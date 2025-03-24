import pytest
import os
import io
from pathlib import Path
from zipfile import ZipFile

import tools
import problem
import config
import util

# Run `bt run` on these problems.
PROBLEMS = [
    "hello",
    "helloproblemtools",
    "different",
    "fltcmp",
    "boolfind",
    "guess",
    "divsort",
    "interactivemultipass",
    "multipass",
    "constants",
] + ["hellounix" if not util.is_mac() and not util.is_windows() else []]

RUN_DIR = Path.cwd().resolve()


@pytest.fixture(scope="class", params=PROBLEMS)
def setup_problem(request):
    problemname = request.param
    problem_dir = RUN_DIR / "test/problems" / problemname
    os.chdir(problem_dir)
    yield
    tools.test(["tmp", "--clean"])
    os.chdir(RUN_DIR)


@pytest.mark.usefixtures("setup_problem")
class TestProblem:
    def test_problem(self):
        tools.test(["run"])


@pytest.fixture(scope="class")
def setup_constants_problem(request):
    problem_dir = RUN_DIR / "test/problems/constants"
    os.chdir(problem_dir)
    try:
        tools.test(["tmp", "--clean"])
        yield
    finally:
        tools.test(["tmp", "--clean"])
        os.chdir(RUN_DIR)


@pytest.mark.usefixtures("setup_constants_problem")
class TestConstantsProblem:
    def test_generate(self):
        tools.test(["generate"])

    def test_pdf(self):
        tools.test(["pdf"])

    def test_solutions(self):
        tools.test(["solutions"])

    def test_problem_slides(self):
        tools.test(["problem_slides"])

    def test_validate(self):
        tools.test(["validate"])

    def test_zip(self):
        tools.test(["zip", "--force"])
        Path("constants.zip").unlink()


@pytest.fixture(scope="class")
def setup_identity_problem(request):
    problem_dir = RUN_DIR / "test/problems/identity"
    os.chdir(problem_dir)
    try:
        tools.test(["tmp", "--clean"])
        yield
    finally:
        tools.test(["tmp", "--clean"])
        os.chdir(RUN_DIR)


@pytest.mark.usefixtures("setup_identity_problem")
class TestIdentityProblem:
    # Development
    def test_generate(self):
        tools.test(["generate"])

    def test_run(self):
        tools.test(["run"])
        # pass testcases
        tools.test(["run", "data/sample"])
        tools.test(["run", "data/secret/seeding", "data/sample/1.in"])
        # pass submission
        tools.test(["run", "submissions/accepted/author.cpp"])
        # pass submissions + testcases
        tools.test(["run", "data/sample/1.in", "submissions/accepted/author.cpp"])
        tools.test(
            [
                "run",
                "submissions/accepted/author.c",
                "submissions/accepted/author.cpp",
                "--samples",
            ],
        )

    def test_test(self):
        tools.test(["test", "submissions/accepted/author.c"])
        tools.test(["test", "submissions/accepted/author.c", "--samples"])
        tools.test(["test", "submissions/accepted/author.c", "data/sample"])
        tools.test(["test", "submissions/accepted/author.c", "data/sample/1.in"])
        tools.test(["test", "submissions/accepted/author.c", "data/sample/1.ans"])
        tools.test(["test", "submissions/accepted/author.c", "data/sample/1", "data/sample/2"])

    def test_pdf(self):
        tools.test(["pdf"])

    def test_solutions(self):
        tools.test(["solutions"])

    def test_problem_slides(self):
        tools.test(["problem_slides"])

    def test_stats(self):
        tools.test(["stats"])

    # Validation
    # def test_input(self): tools.test(['input'])
    # def test_output(self): tools.test(['output'])
    def test_validate(self):
        tools.test(["validate"])

    def test_constraints(self):
        tools.test(["constraints", "-e"])

    # Exporting
    def test_samplezip(self):
        tools.test(["samplezip"])
        zip_path = Path("samples.zip")

        # Sample zip should contain exactly one .in and .ans file.
        assert sorted(
            (info.filename, info.file_size)
            for info in ZipFile(zip_path).infolist()
            if info.filename.startswith("A/")
        ) == [
            (f"A/{i}.{ext}", size)
            for i, size in enumerate([2, 4, 2, 5, 2, 2], start=1)
            for ext in ["ans", "in"]
        ], "Sample zip contents are not correct"

        zip_path.unlink()

    def test_zip(self):
        tools.test(["zip", "--force"])
        zip_path = Path("identity.zip")

        # The full zip should contain the samples with the original file extensions.
        assert sorted(
            (info.filename, info.file_size)
            for info in ZipFile(zip_path).infolist()
            if info.filename.startswith("identity/data/sample/")
        ) == [
            *(
                (f"identity/data/sample/{i}.{ext}", size)
                for i, size in enumerate([2, 4, 2, 5], start=1)
                for ext in ["ans", "in"]
            ),
            *((f"identity/data/sample/5.{ext}", 2) for ext in ["ans", "in", "out"]),
            *((f"identity/data/sample/6.{ext}.statement", 2) for ext in ["ans", "in"]),
        ], "Zip contents for data/sample/ are not correct"

        zip_path.unlink()

    # Misc
    # def test_all(self): tools.test(['all'])
    def test_sort(self):
        tools.test(["sort"])
        tools.test(["sort", "--problem", "."])
        tools.test(["sort", "--problem", str(Path().cwd())])
        tools.test(["sort", "--contest", ".."])
        tools.test(["sort", "--contest", str(Path.cwd().parent)])

    def test_tmp(self):
        tools.test(["tmp"])

    @pytest.mark.parametrize(
        "bad_submission",
        Path(RUN_DIR / "test/problems/identity/submissions").glob("*/*.bad.*"),
    )
    def test_bad_submission(self, bad_submission):
        with pytest.raises(SystemExit):
            tools.test(["run", str(bad_submission)])


@pytest.fixture(scope="class")
def setup_contest(request):
    contest_dir = RUN_DIR / "test/problems"
    os.chdir(contest_dir)
    yield
    tools.test(["tmp", "--clean"])
    os.chdir(RUN_DIR)


@pytest.mark.usefixtures("setup_contest")
class TestContest:
    def test_stats(self):
        tools.test(["stats"])

    def test_sort(self):
        tools.test(["sort"])
        tools.test(["sort", "--contest", "."])
        tools.test(["sort", "--contest", str(Path.cwd())])
        tools.test(["sort", "--problem", "identity"])
        tools.test(["sort", "--problem", str(Path.cwd() / "identity")])

    def test_pdf(self):
        tools.test(["pdf"])

    def test_solutions(self):
        tools.test(["solutions"])

    def test_problem_slides(self):
        tools.test(["problem_slides"])

    def test_gitlabci(self):
        tools.test(["gitlabci"])


@pytest.fixture(scope="function")
def tmp_contest_dir(tmp_path):
    os.chdir(tmp_path)
    yield
    os.chdir(RUN_DIR)


@pytest.mark.usefixtures("tmp_contest_dir")
class TestNewContestProblem:
    def test_new_contest_problem(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("\n\n\n\n\n\n\n\n\n\n\n\n\n\n"))
        tools.test(["new_contest", "contest_name"])
        tools.test(
            [
                "new_problem",
                "--contest",
                "contest_name",
                "Problem One",
                "--author",
                "Ragnar Groot Koerkamp",
                "--type",
                "pass-fail",
            ]
        )
        os.chdir("contest_name")
        monkeypatch.setattr("sys.stdin", io.StringIO("Ragnar Groot Koerkamp\ncustom\n\n\n\n\n\n\n"))
        tools.test(["new_problem", "Problem Two"])
        os.chdir("..")
        problemsyaml = Path("contest_name/problems.yaml").read_text()
        assert "id: problemone" in problemsyaml
        assert "id: problemtwo" in problemsyaml

        with pytest.raises(SystemExit):
            tools.test(["pdf", "--contest", "contest_name"])
        assert config.n_warn == 2
        assert Path("contest_name/contest.en.pdf").is_file()
        tools.test(["solutions", "--contest", "contest_name"])
        tools.test(["problem_slides", "--contest", "contest_name"])
        tools.test(["tmp", "--clean", "--contest", "contest_name"])


class TestReadProblemConfig:
    def test_read_problem_config(self):
        p = problem.Problem(RUN_DIR / "test/problems/testproblemconfig", Path("/tmp/xyz"))
        assert p.settings.name["en"] == "ABC XYZ"
        assert p.custom_output and not p.interactive and not p.multi_pass
        assert p.limits.time_limit == 3.0
