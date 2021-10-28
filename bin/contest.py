from pathlib import Path
from util import *
import json

# Optional, only needed for API stuff
try:
    import requests
except:
    pass

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


_problems_yaml = None


def problems_yaml():
    global _problems_yaml
    if _problems_yaml:
        return _problems_yaml
    if _problems_yaml is False:
        return None

    problemsyaml_path = Path('problems.yaml')
    if not problemsyaml_path.is_file():
        _problems_yaml = False
        return None
    _problems_yaml = read_yaml(problemsyaml_path)
    return _problems_yaml


def get_api():
    api = None
    if getattr(config.args, 'api', None):
        api = config.args.api
    else:
        if contest_yaml() is None or 'api' not in contest_yaml():
            fatal(
                'Could not find key `api` in contest.yaml and it was not specified on the command line.'
            )
        api = contest_yaml()['api']
    if not api.endswith('/'):
        api += '/'
    api += 'api/v4'
    return api


def get_contest_id():
    if getattr(config.args, 'contest_id', None):
        return config.args.contest_id
    if contest_yaml() and contest_yaml().get('contest_id', None):
        return contest_yaml()['contest_id']
    url = f'{get_api()}/contests'
    verbose(f'query {url}')
    r = call_api('GET', '/contests')
    r.raise_for_status()
    contests = json.loads(r.text)
    assert isinstance(contests, list)
    if len(contests) != 1:
        for contest in contests:
            log(f'{contest["id"]}: {contest["name"]}')
        fatal(
            'Server has multiple active contests. Pass --contest-id <cid> or set it in contest.yaml.'
        )
    log(f'The only active contest has id {contests[0]["id"]}')
    return contests[0]['id']


def call_api(method, endpoint, **kwargs):
    url = get_api() + endpoint
    verbose(f'{method} {url}')
    r = requests.request(
        method,
        url,
        auth=requests.auth.HTTPBasicAuth(config.args.username, config.args.password),
        **kwargs,
    )

    if not r.ok:
        error(r.text)
    return r
