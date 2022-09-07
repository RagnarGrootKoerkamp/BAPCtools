import requests

from util import *

# Function to create a slack channel for each problem
def create_slack_channels(problems):
    for p in problems:
        create_slack_channel(p.name)


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
