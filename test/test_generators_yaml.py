import pytest
import yaml
from pathlib import Path

import generate
import config

config.RUNNING_TEST = True


class MockProblem:
    def __init__(self):
        self.path = Path('.')
        self._program_callbacks = dict()
        self._rules_cache = dict()


class MockGeneratorConfig(generate.GeneratorConfig):
    def __init__(self, problem):
        self.problem = problem


class TestGeneratorConfig:
    @pytest.mark.parametrize(
        'yamldoc',
        yaml.load_all(
            Path('test/generator_yaml/bad_generators.yaml').read_text(), Loader=yaml.SafeLoader
        ),
    )
    def test_bad_generators_yamls(self, yamldoc):
        with pytest.raises(SystemExit) as e:
            MockGeneratorConfig(MockProblem()).parse_yaml(yamldoc)
