from util import *


# Function to create a slack channel for each problem
def create_slack_channels(problems):
    for p in problems:
        create_slack_channel(p.name)


# The slack user token is of the form xoxp-...
def create_slack_channel(name):
    verbose(f'Creating channel {name}')
    r = call_slack_api('conversations.create', name=name)
    if not r.ok:
        error(r.text)
        return
    response = r.json()
    if not response['ok']:
        error(response['error'])
        return
    log(f'Created and joined channel {name}')


def join_slack_channels(problems):
    verbose('Reading conversations list')
    r = call_slack_api('conversations.list').json()
    if not r['ok']:
        error(r['error'])
        return

    channel_ids = {}
    for c in r['channels']:
        channel_ids[c['name']] = c['id']

    for p in problems:
        join_slack_channel(p.name, channel_ids[p.name])


def join_slack_channel(name, id):
    verbose(f'joining channel {name} id {id}')
    r = call_slack_api('conversations.join', channel=id)
    if not r.ok:
        error(r.text)
        return
    response = r.json()
    if not response['ok']:
        error(response['error'])
        return
    log(f'Created and joined channel {name}')


def call_slack_api(path, **kwargs):
    import requests  # Slow import, so only import it inside this function.

    return requests.post(
        f'https://slack.com/api/{path}',
        {'token': config.args.token, **kwargs},
    )
