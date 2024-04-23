import pytest
import yaml
import os
import io
from pathlib import Path

import tools
import problem
import config
import util

# Run `bt run` on these problems.
PROBLEMS = ['hello', 'helloproblemtools', 'different', 'fltcmp', 'boolfind', 'guess', 'divsort', 'interactivemultipass', 'multipass'] + [
    'hellounix' if not util.is_mac() and not util.is_windows() else []
]

# Run various specific commands on this problem.
IDENTITY_PROBLEMS = ['identity']

RUN_DIR = Path.cwd().resolve()


@pytest.fixture(scope='class', params=PROBLEMS)
def setup_problem(request):
    problemname = request.param
    problem_dir = RUN_DIR / 'test/problems' / problemname
    os.chdir(problem_dir)
    yield
    tools.test(['tmp', '--clean'])
    os.chdir(RUN_DIR)


@pytest.mark.usefixtures('setup_problem')
class TestProblem:
    def test_problem(self):
        tools.test(['run'])


@pytest.fixture(scope='class')
def setup_identity_problem(request):
    problem_dir = RUN_DIR / 'test/problems/identity'
    os.chdir(problem_dir)
    try:
        tools.test(['tmp', '--clean'])
        yield
    finally:
        tools.test(['tmp', '--clean'])
        os.chdir(RUN_DIR)


@pytest.mark.usefixtures('setup_identity_problem')
class TestIdentityProblem:
    # Development
    def test_generate(self):
        tools.test(['generate'])

    def test_run(self):
        tools.test(['run'])
        # pass testcases
        tools.test(['run', 'data/sample'])
        tools.test(['run', 'data/secret/seeding', 'data/sample/1.in'])
        # pass submission
        tools.test(['run', 'submissions/accepted/author.cpp'])
        # pass submissions + testcases
        tools.test(['run', 'data/sample/1.in', 'submissions/accepted/author.cpp'])
        tools.test(
            ['run', 'submissions/accepted/author.c', 'submissions/accepted/author.cpp', '--samples']
        )

    def test_test(self):
        tools.test(['test', 'submissions/accepted/author.c'])
        tools.test(['test', 'submissions/accepted/author.c', '--samples'])
        tools.test(['test', 'submissions/accepted/author.c', 'data/sample'])
        tools.test(['test', 'submissions/accepted/author.c', 'data/sample/1.in'])
        tools.test(['test', 'submissions/accepted/author.c', 'data/sample/1.ans'])
        tools.test(['test', 'submissions/accepted/author.c', 'data/sample/1', 'data/sample/2'])

    def test_pdf(self):
        tools.test(['pdf'])

    def test_stats(self):
        tools.test(['stats'])

    # Validation
    # def test_input(self): tools.test(['input'])
    # def test_output(self): tools.test(['output'])
    def test_validate(self):
        tools.test(['validate'])

    def test_constraints(self):
        tools.test(['constraints', '-e'])

    # Exporting
    def test_samplezip(self):
        tools.test(['samplezip'])
        Path('samples.zip').unlink()

    def test_zip(self):
        tools.test(['zip', '--force'])
        Path('identity.zip').unlink()

    # Misc
    # def test_all(self): tools.test(['all'])
    def test_sort(self):
        tools.test(['sort'])
        tools.test(['sort', '--problem', '.'])
        tools.test(['sort', '--problem', str(Path().cwd())])
        tools.test(['sort', '--contest', '..'])
        tools.test(['sort', '--contest', str(Path.cwd().parent)])

    def test_tmp(self):
        tools.test(['tmp'])

    @pytest.mark.parametrize(
        'bad_submission', Path(RUN_DIR / 'test/problems/identity/submissions').glob('*/*.bad.*')
    )
    def test_bad_submission(self, bad_submission):
        with pytest.raises(SystemExit) as e:
            tools.test(['run', str(bad_submission)])


@pytest.fixture(scope='class')
def setup_contest(request):
    contest_dir = RUN_DIR / 'test/problems'
    os.chdir(contest_dir)
    yield
    tools.test(['tmp', '--clean'])
    os.chdir(RUN_DIR)


@pytest.mark.usefixtures('setup_contest')
class TestContest:
    def test_stats(self):
        tools.test(['stats'])

    def test_sort(self):
        tools.test(['sort'])
        tools.test(['sort', '--contest', '.'])
        tools.test(['sort', '--contest', str(Path.cwd())])
        tools.test(['sort', '--problem', 'identity'])
        tools.test(['sort', '--problem', str(Path.cwd() / 'identity')])

    def test_pdf(self):
        tools.test(['pdf'])

    def test_solutions(self):
        tools.test(['solutions'])

    def test_gitlabci(self):
        tools.test(['gitlabci'])


@pytest.fixture(scope='function')
def tmp_contest_dir(tmp_path):
    os.chdir(tmp_path)
    yield
    os.chdir(RUN_DIR)


@pytest.mark.usefixtures('tmp_contest_dir')
class TestNewContestProblem:
    def test_new_contest_problem(self, monkeypatch):
        monkeypatch.setattr('sys.stdin', io.StringIO('\n\n\n\n\n\n\n\n\n\n\n\n\n\n'))
        tools.test(['new_contest', 'contest_name'])
        tools.test(
            [
                'new_problem',
                '--contest',
                'contest_name',
                'Problem One',
                '--author',
                'Ragnar Groot Koerkamp',
                '--validation',
                'default',
            ]
        )
        os.chdir('contest_name')
        monkeypatch.setattr('sys.stdin', io.StringIO('Ragnar Groot Koerkamp\ncustom\n\n\n\n\n\n\n'))
        tools.test(['new_problem', 'Problem Two'])
        os.chdir('..')
        problemsyaml = Path('contest_name/problems.yaml').read_text()
        assert 'id: problemone' in problemsyaml
        assert 'id: problemtwo' in problemsyaml

        with pytest.raises(SystemExit) as e:
            tools.test(['pdf', '--contest', 'contest_name'])
        assert config.n_warn == 2
        assert Path('contest_name/contest.en.pdf').is_file()
        tools.test(['solutions', '--contest', 'contest_name'])
        tools.test(['tmp', '--clean', '--contest', 'contest_name'])


class TestReadProblemConfig:
    def test_read_problem_config(self):
        p = problem.Problem(RUN_DIR / 'test/problems/test_problem_config', Path('/tmp/xyz'))
        assert p.settings.name['en'] == 'ABC XYZ'
        assert p.settings.validation == 'custom'
        assert p.settings.timelimit == 3.0
