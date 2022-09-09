try:
    import requests
except:
    pass

from util import *

# Function to create a slack channel for each problem
def create_slack_channels(problems):
    for p in problems:
        create_slack_channel(p.name)


# The slack user token is of the form xoxp-...
def create_slack_channel(name):
    verbose(f'Creating channel {name}')
    r = requests.post(
        'https://slack.com/api/conversations.create',
        {
            'token': config.args.token,
            'name': name,
        },
    )
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
    r = requests.post(
        'https://slack.com/api/conversations.list',
        {
            'token': config.args.token,
        },
    ).json()
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
    r = requests.post(
        'https://slack.com/api/conversations.join',
        {
            'token': config.args.token,
            'channel': id,
        },
    )
    if not r.ok:
        error(r.text)
        return
    response = r.json()
    if not response['ok']:
        error(response['error'])
        return
    log(f'Created and joined channel {name}')
