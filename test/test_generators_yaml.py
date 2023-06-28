import argparse
import collections
import pytest
import yaml
from pathlib import Path

import generate
import config

config.RUNNING_TEST = True
config.set_default_args()


class MockProblem:
    def __init__(self):
        self.path = Path('.')
        self._program_callbacks = dict()
        self._rules_cache = dict()


class MockGeneratorConfig(generate.GeneratorConfig):
    def __init__(self, problem):
        self.problem = problem

        # A map of paths `secret/testgroup/testcase` to their canonical TestcaseRule.
        # For generated cases this is the rule itself.
        # For included cases, this is the 'resolved' location of the testcase that is included.
        self.known_cases = dict()
        # A set of paths `secret/testgroup`.
        # Used for cleanup.
        self.known_directories = set()
        # A map from key to (is_included, list of testcases and directories),
        # used for `include` statements.
        self.known_keys = collections.defaultdict(lambda: [False, []])
        # A set of testcase rules, including seeds.
        self.rules_cache = dict()
        # The set of generated testcases keyed by testdata.
        # Used to delete duplicated unlisted manual cases.
        self.generated_testdata = dict()


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
