from util import *

# Perform slack actions for the selected problems (all, or the selected/current one).
# - create a slack channel
# - join slack channel
#
# Requires a 'user token' (https://api.slack.com/authentication/token-types).
# To obtain this token, create a new app (https://api.slack.com/apps) and add it to your workspace.
# Use the 'Bot User OAuth Token' under OAuth & Permissions.
# It can be passed as `--token <token>` or stored in `.bapctools.yaml` as `token: <token>`.


def call_slack_api(path, **kwargs):
    import requests  # Slow import, so only import it inside this function.

    verbose(f'Calling slack api {path}')
    result = requests.post(
        f'https://slack.com/api/{path}',
        {'token': config.args.token, **kwargs},
    )

    if not result.json()['ok'] and result.json()['error'] == 'ratelimited':
        fatal('Slack API rate limit exceeded. Try again later.')

    return result


def get_channel_ids():
    r = call_slack_api('conversations.list').json()
    if not r['ok']:
        fatal(r['error'])

    channel_ids = {}
    for c in r['channels']:
        channel_ids[c['name']] = c['id']
    return channel_ids


def get_user_id(username):
    r = call_slack_api('users.list').json()
    if not r['ok']:
        fatal(r['error'])
    members = r['members']
    for m in members:
        if m['profile']['real_name'] == username or m['profile']['display_name'] == username:
            return m['id']
    fatal(f'User {username} not found')


# Function to create a slack channel for each problem
def create_slack_channels(problems):
    for p in problems:
        create_slack_channel(p.name)


def create_slack_channel(name):
    r = call_slack_api('conversations.create', name=name)
    if not r.ok:
        error(r.text)
        return
    response = r.json()
    if not response['ok']:
        error(response['error'])
        return
    log(f'Created channel {name}')


def join_slack_channels(problems, username):
    userid = get_user_id(username)
    channel_ids = get_channel_ids()

    for p in problems:
        join_slack_channel(p.name, channel_ids[p.name], username, userid)


def join_slack_channel(channel_name, channel_id, username, userid):
    # The bot account invites the user to the channel.
    r = call_slack_api('conversations.invite', channel=channel_id, users=userid)
    if not r.ok:
        error(r.text)
        return
    response = r.json()
    if not response['ok']:
        error(response['error'])
        return
    log(f'Invited {username} to channel {channel_name}')
