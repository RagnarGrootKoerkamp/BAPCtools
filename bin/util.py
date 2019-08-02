# read problem settings from config files
def read_configs(problem):
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
    if yamlpath.is_file():
        with yamlpath.open() as yamlfile:
            try:
                config = yaml.load(yamlfile)
                for key, value in config.items():
                    settings[key] = value
            except:
                pass

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

    # parse domjudge-problem.ini
    domjudge_path = problem / 'domjudge-problem.ini'
    if domjudge_path.is_file():
        with domjudge_path.open() as f:
            for line in f.readlines():
                key, var = line.strip().split('=')
                var = var[1:-1]
                settings[key] = float(var) if key == 'timelimit' else var

    return settings


# sort problems by the id in domjudge-problem.ini, and secondary by name
# return [(problem, id)]
def sort_problems(problems):
    configs = [(problem, read_configs(problem)) for problem in problems]
    problems = [(pair[0], pair[1]['probid']) for pair in configs if 'probid' in pair[1]]
    problems.sort(key=lambda x: (x[1], x[0]))
    return problems


# testcases; returns list of basenames
def get_testcases(problem, needans=True, only_sample=False):
    infiles = list(problem.glob('data/sample/*.in'))
    if not only_sample:
        infiles += list(problem.glob('data/secret/*.in'))

    testcases = []
    for f in infiles:
        if needans and not f.with_suffix('.ans').is_file():
            continue
        testcases.append(f.with_suffix(''))
    testcases.sort()

    return testcases
