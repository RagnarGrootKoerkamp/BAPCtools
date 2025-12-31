import io
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from bapctools import cli, config, problem, util

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
    "testexpectations",
    "alternativeencryption",
    "testseed",
    "generatorcount",
    "generatorincludes",
]
if not util.is_mac() and not util.is_windows():
    PROBLEMS += ["hellounix"]

RUN_DIR = Path.cwd().absolute()


def _setup_problem(problemname):
    problem_dir = RUN_DIR / "test/problems" / problemname
    os.chdir(problem_dir)
    yield
    cli.test(["tmp", "--clean"])
    os.chdir(RUN_DIR)


@pytest.fixture(scope="class", params=PROBLEMS)
def setup_problem(request):
    yield from _setup_problem(request.param)


@pytest.mark.usefixtures("setup_problem")
class TestProblem:
    def test_problem(self):
        cli.test(["run"])


@pytest.fixture(scope="class")
def setup_alternativeencryption_problem(request):
    yield from _setup_problem("alternativeencryption")


@pytest.mark.usefixtures("setup_alternativeencryption_problem")
class TestAlternativeencryptionProblem:
    def test_generate(self):
        cli.test(["generate"])

    def test_check_testing_tool(self):
        cli.test(["check_testing_tool"])

    def test_bad_check_testing_tool(self):
        with pytest.raises(SystemExit):
            cli.test(["check_testing_tool", "submissions/wrong_answer/no-change.py"])


@pytest.fixture(scope="class")
def setup_constants_problem(request):
    yield from _setup_problem("constants")


@pytest.mark.usefixtures("setup_constants_problem")
class TestConstantsProblem:
    def test_generate(self):
        cli.test(["generate"])

    def test_pdf(self):
        cli.test(["pdf"])

    def test_solutions(self):
        cli.test(["solutions"])

    def test_problem_slides(self):
        cli.test(["problem_slides"])

    def test_validate(self):
        cli.test(["validate"])

    def test_zip(self):
        cli.test(["zip", "--force"])
        Path("constants.zip").unlink()


@pytest.fixture(scope="class")
def setup_identity_problem(request):
    yield from _setup_problem("identity")


@pytest.mark.usefixtures("setup_identity_problem")
class TestIdentityProblem:
    # Development
    def test_generate(self):
        cli.test(["generate"])

    def test_run(self):
        cli.test(["run"])
        # pass testcases
        cli.test(["run", "data/sample"])
        cli.test(["run", "data/secret/seeding", "data/sample/1.in"])
        # pass submission
        cli.test(["run", "submissions/accepted/author.cpp"])
        # pass submissions + testcases
        cli.test(["run", "data/sample/1.in", "submissions/accepted/author.cpp"])
        cli.test(
            [
                "run",
                "submissions/accepted/author.c",
                "submissions/accepted/author.cpp",
                "--samples",
            ],
        )

    def test_test(self):
        cli.test(["test", "submissions/accepted/author.c"])
        cli.test(["test", "submissions/accepted/author.c", "--samples"])
        cli.test(["test", "submissions/accepted/author.c", "data/sample"])
        cli.test(["test", "submissions/accepted/author.c", "data/sample/1.in"])
        cli.test(["test", "submissions/accepted/author.c", "data/sample/1.ans"])
        cli.test(["test", "submissions/accepted/author.c", "data/sample/1", "data/sample/2"])

    def test_pdf(self):
        cli.test(["pdf"])

    def test_solutions(self):
        cli.test(["solutions"])

    def test_problem_slides(self):
        cli.test(["problem_slides"])

    def test_stats(self):
        cli.test(["stats"])

    # Validation
    # def test_input(self): tools.test(['input'])
    # def test_output(self): tools.test(['output'])
    def test_validate(self):
        cli.test(["validate"])

    def test_constraints(self):
        cli.test(["constraints", "-e"])

    # Exporting
    def test_samplezip(self):
        cli.test(["samplezip"])
        zip_path = Path("samples.zip")

        # Sample zip should contain exactly one .in and .ans file.
        assert sorted(
            (info.filename, info.file_size)
            for info in ZipFile(zip_path).infolist()
            if info.filename.startswith("A/")
        ) == [
            ("A/", 0),
            *(
                (f"A/{i}.{ext}", size)
                for i, size in enumerate([2, 4, 2, 5, 2, 2], start=1)
                for ext in ["ans", "in"]
            ),
        ], "Sample zip contents are not correct"

        zip_path.unlink()

    def test_zip(self):
        zip_path = Path("identity.zip")

        cli.test(["zip", "--force"])

        # The full zip should contain the samples with the original file extensions.
        assert sorted(
            (info.filename, info.file_size)
            for info in ZipFile(zip_path).infolist()
            if info.filename.startswith("identity/data/sample/")
        ) == [
            ("identity/data/sample/", 0),
            *(
                (f"identity/data/sample/{i}.{ext}", size)
                for i, size in enumerate([2, 4, 2, 5], start=1)
                for ext in ["ans", "in"]
            ),
            *((f"identity/data/sample/5.{ext}", 2) for ext in ["ans", "in", "out"]),
            *((f"identity/data/sample/6.ans.{ext}", 2) for ext in ["download", "statement"]),
            *((f"identity/data/sample/6.in.{ext}", 2) for ext in ["download", "statement"]),
        ], "Zip contents for data/sample/ are not correct"

        # The full zip should contain all PDFs in their corresponding directories.
        assert sorted(
            info.filename for info in ZipFile(zip_path).infolist() if info.filename.endswith(".pdf")
        ) == [
            f"identity/{path}.{lang}.pdf"
            for path in [
                "problem_slide/problem-slide",
                "solution/solution",
                "statement/problem",
            ]
            for lang in ["de", "en"]
        ], "Zip contents for PDFs with both languages are not correct"

        cli.test(["zip", "--force", "--lang", "en"])

        # The full zip should contain all PDFs in their corresponding directories.
        assert sorted(
            info.filename for info in ZipFile(zip_path).infolist() if info.filename.endswith(".pdf")
        ) == [
            f"identity/{path}.en.pdf"
            for path in [
                "problem_slide/problem-slide",
                "solution/solution",
                "statement/problem",
            ]
        ], "Zip contents for PDFs with `--lang en` are not correct"

        zip_path.unlink()

    # Misc
    # def test_all(self): tools.test(['all'])
    def test_sort(self):
        cli.test(["sort"])
        cli.test(["sort", "--problem", "."])
        cli.test(["sort", "--problem", str(Path().cwd())])
        cli.test(["sort", "--contest", ".."])
        cli.test(["sort", "--contest", str(Path.cwd().parent)])

    def test_tmp(self):
        cli.test(["tmp"])

    @pytest.mark.parametrize(
        "bad_submission",
        Path(RUN_DIR / "test/problems/identity/submissions").glob("*/*.bad.*"),
    )
    def test_bad_submission(self, bad_submission):
        with pytest.raises(SystemExit):
            cli.test(["run", str(bad_submission)])


@pytest.fixture(scope="class")
def setup_contest(request):
    contest_dir = RUN_DIR / "test/problems"
    os.chdir(contest_dir)
    yield
    cli.test(["tmp", "--clean"])
    os.chdir(RUN_DIR)


@pytest.mark.usefixtures("setup_contest")
class TestContest:
    def test_stats(self):
        cli.test(["stats"])

    def test_sort(self):
        cli.test(["sort"])
        cli.test(["sort", "--contest", "."])
        cli.test(["sort", "--contest", str(Path.cwd())])
        cli.test(["sort", "--problem", "identity"])
        cli.test(["sort", "--problem", str(Path.cwd() / "identity")])

    def test_pdf(self):
        cli.test(["pdf"])

    def test_solutions(self):
        cli.test(["solutions"])

    def test_problem_slides(self):
        cli.test(["problem_slides"])

    def test_gitlabci(self):
        cli.test(["gitlabci"])

    def test_zip(self):
        zip_path = Path("problems.zip")

        for languages in [["en", "de"], ["en"]]:
            cli.test(["zip", "--force", "--lang", *languages])

            # The full zip should contain all PDFs in their corresponding directories.
            assert sorted(info.filename for info in ZipFile(zip_path).infolist()) == sorted(
                [
                    "contest.yaml",
                    "identity.zip",
                    "problems.yaml",
                    "samples.zip",
                    *(
                        f"{name}{suffix}.{lang}.pdf"
                        for name in ["contest", "solutions", "problem-slides"]
                        for lang in languages
                        for suffix in ["", "-web"]
                        # The problem slides do not have a -web version.
                        if (name, suffix) != ("problem-slides", "-web")
                    ),
                ]
            ), f"Zip contents for contest zip are not correct for languages {languages}"

        zip_path.unlink()
        Path("identity/identity.zip").unlink()
        Path("samples.zip").unlink()


@pytest.fixture(scope="function")
def tmp_contest_dir(tmp_path):
    os.chdir(tmp_path)
    yield
    os.chdir(RUN_DIR)


@pytest.mark.usefixtures("tmp_contest_dir")
class TestNewContestProblem:
    def test_new_contest_problem(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("\n\n\n\n\n\n\n\n\n\n\n\n\n\n"))
        cli.test(["new_contest", "contest_name"])
        cli.test(
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
        cli.test(["new_problem", "Problem Two"])
        os.chdir("..")
        problemsyaml = Path("contest_name/problems.yaml").read_text()
        assert "id: problemone" in problemsyaml
        assert "id: problemtwo" in problemsyaml

        with pytest.raises(SystemExit):
            cli.test(["pdf", "--contest", "contest_name"])
        assert config.n_warn == 2
        assert Path("contest_name/contest.en.pdf").is_file()
        cli.test(["solutions", "--contest", "contest_name"])
        cli.test(["problem_slides", "--contest", "contest_name"])
        cli.test(["tmp", "--clean", "--contest", "contest_name"])


class TestReadProblemConfig:
    def test_read_problem_config(self):
        p = problem.Problem(RUN_DIR / "test/problems/testproblemconfig", Path("/tmp/xyz"))
        assert p.settings.name["en"] == "ABC XYZ"
        assert p.custom_output and not p.interactive and not p.multi_pass
        assert p.limits.time_limit == 3.0
