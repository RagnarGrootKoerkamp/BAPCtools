from pathlib import Path
import re
import util


# A problem.
class Problem:
    _shortname_regex = re.compile('^[a-z0-9]+$')

    def __init__(self, path, label = 'A'):
        # The problem id (shortname). This is also the name of the problem directory.
        self.id = path.resolve().name
        # The label for the problem: A, B, A1, A2, X, ...
        self.label = label
        # The Path of the problem directory.
        self.path = path
        # Configuration in problem.yaml
        self.config = Problem._read_configs(self.path)

        # TODO: transform this into nice warnings
        assert path.is_dir()
        assert Problem._shortname_regex.match(self.id)


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
        for k, v in util.read_yaml(problem / 'problem.yaml').items():
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
