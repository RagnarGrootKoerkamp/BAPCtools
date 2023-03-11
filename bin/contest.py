from pathlib import Path
import json

from util import *

# Read the contest.yaml, if available
_contest_yaml = None


def contest_yaml():
    global _contest_yaml
    if _contest_yaml is not None:
        return _contest_yaml

    # TODO: Do we need both here?
    for p in ['contest.yaml', '../contest.yaml']:
        p = Path(p)
        if p.is_file():
            _contest_yaml = read_yaml_settings(p)
            return _contest_yaml
    _contest_yaml = {}
    return _contest_yaml


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
    api = config.args.api or contest_yaml().get('api')
    if not api:
        fatal(
            'Could not find key `api` in contest.yaml and it was not specified on the command line.'
        )
    if api.endswith('/'):
        api = api[:-1]
    if not api.endswith('/api/v4'):
        api += '/api/v4'
    return api


def get_contest_id():
    if config.args.contest_id:
        return config.args.contest_id
    if 'contest_id' in contest_yaml():
        return contest_yaml()['contest_id']
    contests = get_contests()
    if len(contests) > 1:
        for contest in contests:
            log(f'{contest["id"]}: {contest["name"]}')
        fatal(
            'Server has multiple active contests. Pass --contest-id <cid> or set it in contest.yaml.'
        )
    if len(contests) == 1:
        log(f'The only active contest has id {contests[0]["id"]}')
        return contests[0]['id']


def get_contests():
    url = f'{get_api()}/contests'
    verbose(f'query {url}')
    r = call_api('GET', '/contests')
    r.raise_for_status()
    contests = json.loads(r.text)
    assert isinstance(contests, list)
    return contests


def call_api(method, endpoint, **kwargs):
    import requests  # Slow import, so only import it inside this function.

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
