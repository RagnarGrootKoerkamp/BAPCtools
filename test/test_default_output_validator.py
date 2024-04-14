import pytest
import argparse
import yaml
import os
import hashlib
import tempfile
from pathlib import Path

import problem
import run
import testcase
import validate
import util
import config

RUN_DIR = Path.cwd().resolve()
# Note: the python version isn't tested by default, because it's quite slow.
DEFAULT_OUTPUT_VALIDATORS = ['default_output_validator.cpp']

config.args.verbose = 2
config.args.error = True
config.set_default_args()


# return list of (flags, ans, out, expected result)
def read_tests():
    docs = yaml.load_all(
        (RUN_DIR / 'test/default_output_validator/default_output_validator.yaml').read_text(),
        Loader=yaml.SafeLoader,
    )

    tests = []

    for doc in docs:
        doc['ans'] = str(doc['ans'])
        if 'ac' in doc:
            for out in doc['ac']:
                tests.append((doc['flags'], doc['ans'], str(out), util.ExecStatus.ACCEPTED))
        if 'wa' in doc:
            for out in doc['wa']:
                tests.append((doc['flags'], doc['ans'], str(out), util.ExecStatus.REJECTED))

    print(tests)
    return tests


@pytest.fixture(scope='class', params=DEFAULT_OUTPUT_VALIDATORS)
def validator(request):
    problem_dir = RUN_DIR / 'test/problems/identity'
    os.chdir(problem_dir)

    h = hashlib.sha256(bytes(Path().cwd())).hexdigest()[-6:]
    tmpdir = Path(tempfile.gettempdir()) / ('bapctools_' + h)
    tmpdir.mkdir(exist_ok=True)
    p = problem.Problem(Path('.'), tmpdir)
    validator = validate.OutputValidator(p, RUN_DIR / 'support' / request.param)
    print(util.ProgressBar.current_bar)
    bar = util.ProgressBar('build', max_len=1)
    validator.build(bar)
    bar.finalize()
    yield (p, validator)
    os.chdir(RUN_DIR)


class MockRun:
    pass


@pytest.mark.usefixtures('validator')
class TestDefaultOutputValidators:
    @pytest.mark.parametrize('testdata', read_tests())
    def test_default_output_validators(self, validator, testdata):
        problem, validator = validator
        flags, ans, out, exp = testdata
        flags = flags.split()

        (problem.tmpdir / 'data').mkdir(exist_ok=True, parents=True)
        in_path = problem.tmpdir / 'data/test.in'
        ans_path = problem.tmpdir / 'data/test.ans'
        out_path = problem.tmpdir / 'data/test.out'
        ans_path.write_text(ans)
        out_path.write_text(out)

        in_path.write_text('')

        t = testcase.Testcase(problem, in_path, short_path=Path('test'))
        r = MockRun()
        r.in_path = in_path
        r.out_path = out_path
        r.feedbackdir = problem.tmpdir / 'data'

        problem.settings.validator_flags = flags

        result = validator.run(t, r)
        if result.status != exp:
            print(testdata)
            for k in vars(result):
                print(k, " -> ", getattr(result, k))
        assert result.status == exp
