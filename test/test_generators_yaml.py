import collections
import pytest
import yaml
from pathlib import Path

import generate
import config

config.RUNNING_TEST = True
config.set_default_args()


class MockSettings:
    def __init__(self):
        self.constants = {}


class MockProblem:
    def __init__(self):
        self.path = Path(".")
        self._program_callbacks = dict()
        self._rules_cache = dict()
        self.settings = MockSettings()
        self.interactive = False
        self.multi_pass = False


class MockGeneratorConfig(generate.GeneratorConfig):
    def __init__(self, problem, restriction=None):
        self.problem = problem
        self.n_parse_error = 0

        # A map of paths `secret/test_group/test_case` to their canonical TestcaseRule.
        # For generated cases this is the rule itself.
        # For included cases, this is the 'resolved' location of the test case that is included.
        self.known_cases = dict()
        # A set of paths `secret/test_group`.
        # Used for cleanup.
        self.known_directories = dict()
        # Used for cleanup
        self.known_files = set()
        # A map from key to (is_included, list of test cases and directories),
        # used for `include` statements.
        self.known_keys = collections.defaultdict(lambda: [False, []])
        # A set of testcase rules, including seeds.
        self.rules_cache = dict()
        # The set of generated test cases keyed by hash(test_case).
        # Used to delete duplicated unlisted cases.
        self.generated_test_cases = dict()
        # Path to the trash directory for this run
        self.trash_dir = None
        # Set of hash(.in) for all generated testcases
        self.hashed_in = set()
        # Files that should be processed
        self.restriction = restriction


class TestGeneratorConfig:
    @pytest.mark.parametrize(
        "yamldoc",
        yaml.load_all(
            Path("test/yaml/generators/invalid_yaml/bad_generators.yaml").read_text(),
            Loader=yaml.SafeLoader,
        ),
    )
    def test_bad_generators_yamls(self, yamldoc):
        with pytest.raises(generate.ParseException):
            gen_config = MockGeneratorConfig(MockProblem())
            gen_config.parse_yaml(yamldoc)
            if gen_config.n_parse_error > 0:
                raise generate.ParseException()
