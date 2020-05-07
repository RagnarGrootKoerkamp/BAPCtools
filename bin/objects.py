import re
import glob

from pathlib import Path

import config
from util import *


class Testcase:
    def __init__(self, problem, path):
        assert path.suffix == '.in'

        self.in_path = path
        self.ans_path = path.with_suffix('.ans')
        self.short_path = path.relative_to(problem.path / 'data')

        # Display name: everything after data/.
        self.name = str(self.short_path.with_suffix(''))

    def with_suffix(self, ext):
        return self.in_path.with_suffix(ext)



# A problem.
class Problem:
    _shortname_regex_string = '^[a-z0-9]+$'
    _shortname_regex = re.compile(_shortname_regex_string)

    def __init__(self, path, label=None):
        # The problem name/shortname, which is the name of the directory and used as a display name.
        self.name = path.resolve().name
        # The Path of the problem directory.
        self.path = path
        # Configuration in problem.yaml
        self.config = Problem._read_configs(self.path)
        # This is a Namespace type copy of settings which also includes command line flags.
        self.settings = None

        # TODO: Add and use a new Problem.tmp_dir field.

        # The label for the problem: A, B, A1, A2, X, ...
        if label is None:
            # Use label from the domjudge-problem.ini
            if 'probid' in self.config:
                self.label = self.config['probid']
            else:
                self.label = 'A'
        else:
            self.label = label

        # TODO: transform this into nice warnings
        assert path.is_dir()
        if not Problem._shortname_regex.match(self.name):
            warn(
                f'Problem has a bad shortname: {self.name} does not match {self._shortname_regex_string}'
            )

    # TODO: This should be overridden by command line flags.
    def _read_configs(problem):
        # some defaults
        settings = {
            'timelimit': 1,
            'name': '',
            'floatabs': None,
            'floatrel': None,
            'validation': 'default',
            'case_sensitive': False,
            'space_change_sensitive': False,
            'validator_flags': None
        }

        # parse problem.yaml
        yamlpath = problem / 'problem.yaml'
        yamldata = read_yaml(problem / 'problem.yaml')
        if yamldata:
            for k, v in yamldata.items():
                settings[k] = v

        # parse validator_flags
        if 'validator_flags' in settings and settings['validator_flags']:
            flags = settings['validator_flags'].split(' ')
            i = 0
            while i < len(flags):
                if flags[i] in ['case_sensitive', 'space_change_sensitive']:
                    settings[flags[i]] = True
                elif flags[i] == 'float_absolute_tolerance':
                    settings['floatabs'] = float(flags[i + 1])
                    i += 1
                elif flags[i] == 'float_relative_tolerance':
                    settings['floatrel'] = float(flags[i + 1])
                    i += 1
                elif flags[i] == 'float_tolerance':
                    settings['floatabs'] = float(flags[i + 1])
                    settings['floatrel'] = float(flags[i + 1])
                    i += 1
                i += 1

        # TODO: Get rid of domjudge-problem.ini; it's only remaining use is
        # timelimits.
        # parse domjudge-problem.ini
        domjudge_path = problem / 'domjudge-problem.ini'
        if domjudge_path.is_file():
            with domjudge_path.open() as f:
                for line in f.readlines():
                    key, var = line.strip().split('=')
                    var = var[1:-1]
                    settings[key] = float(var) if key == 'timelimit' else var

        return settings

    _testcases = dict()
    def testcases(p, needans=True, only_sample=False):
        samplesonly = only_sample or config.arg('samples', False)

        key = (needans, samplesonly)
        if key in p._testcases is not None: return p._testcases[key]

        in_paths = None
        # NOTE: Testcases must be specified relative to the problem root.
        if config.arg('testcases'):
            if samplesonly:
                warn(f'Ignoring the --samples flag because testcases are explicitly listed.')
            # Deduplicate testcases with both .in and .ans.
            in_paths = []
            for t in config.args.testcases:
                if Path(p.path / t).is_dir():
                    in_paths += glob(p.path / t, '**/*.in')
                else:
                    t = t.with_suffix('.in')
                    if not t.is_path(): warn(f'Testcase {t} not found.')
                    in_paths.append(p.path / t)

            in_paths = list(set(in_paths))
        else:
            in_paths = list(glob(p.path, 'data/sample/**/*.in'))
            if not samplesonly:
                in_paths += list(glob(p.path, 'data/secret/**/*.in'))

        testcases = []
        for f in in_paths:
            # Require both in and ans files
            if needans and not f.with_suffix('.ans').is_file():
                warn(f'Found input file {str(f)} without a .ans file. Skipping.')
                continue
            testcases.append(Testcase(p, f))
        testcases.sort(key = lambda t: t.name)

        if len(testcases) == 0:
            warn(f'Didn\'t find any testcases for {p.name}')
        p._testcases[key] = testcases
        return p._testcases[key]

