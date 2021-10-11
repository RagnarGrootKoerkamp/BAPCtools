from pathlib import Path
from util import *

# Read the contest.yaml, if available
_contest_yaml = None


def contest_yaml():
    global _contest_yaml
    if _contest_yaml:
        return _contest_yaml
    if _contest_yaml is False:
        return None

    path = None
    # TODO: Do we need both here?
    for p in ['contest.yaml', '../contest.yaml']:
        p = Path(p)
        if p.is_file():
            path = p
            break
    if path is None:
        _contest_yaml = False
        return None
    _contest_yaml = read_yaml_settings(path)
    return _contest_yaml


def next_label(label):
    if label is None:
        return 'A'
    return label[:-1] + chr(ord(label[-1]) + 1)


_problemset_yaml = None


def problemset_yaml():
    global _problemset_yaml
    if _problemset_yaml:
        return _problemset_yaml
    if _problemset_yaml is False:
        return None

    problemsyaml_path = Path('problemset.yaml')
    old_problemsyaml_path = Path('problems.yaml')
    if not problemsyaml_path.is_file() and old_probemyaml_path.is_file():
        verbose('problems.yaml is DEPRECATED. Rename to problemset.yaml instead.')
        problemsyaml_path = old_problemsyaml_path
    if not problemsyaml_path.is_file():
        _problemset_yaml = False
        return None
    _problemset_yaml = read_yaml(problemsyaml_path)
    return _problemset_yaml


def get_api():
    api = None
    if hasattr(config.args, 'api') and config.args.api is not None:
        api = config.args.api
    else:
        if contest_yaml() is None or 'api' not in contest_yaml():
            fatal(
                'Could not find key `api` in contest.yaml and it was not specified on the command line.'
            )
        api = contest_yaml()['api']
    api += '/api/v4'
    return api


def get_contest_id():
    if getattr(config.args, 'contest_id', None):
        return config.args.contest_id
    if contest_yaml() and contest_yaml().get('contest_id', None):
        return contest_yaml()['contest_id']
    url = f'{api}/contests'
    verbose(f'query {url}')
    with urlopen(url) as response:
        contests = json.loads(response.read())
        assert isinstance(contests, list)
        if len(contests) != 1:
            fatal(
                'Server has multiple active contests. Pass --contest-id <cid> or set it in contest.yaml.'
            )
        log(f'The only active contest has id {contests[0]["id"]}')
        return contests[0]['id']
