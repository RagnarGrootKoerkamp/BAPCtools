from os import makedirs
from pathlib import Path

from contest import call_api, get_contest_id
from util import ProgressBar


def generate_solve_stats(post_freeze):
    # Import takes more than 1000 ms to evaluate, so only import inside function (when it is actually needed)
    import matplotlib.pyplot as plt

    contest_id = get_contest_id()

    # The endpoint should not start with a slash
    def req(endpoint):
        url = f'/contests/{contest_id}/{endpoint}'
        bar.start(url)
        r = call_api('GET', url)
        r.raise_for_status()
        bar.done()
        try:
            return r.json()
        except Exception as e:
            print(f'\nError in decoding JSON:\n{e}\n{r.text()}')

    # Turns an endpoint list result into an object, mapped by 'id'
    def req_assoc(endpoint):
        return {o['id']: o for o in req(endpoint)}

    def time_string_to_minutes(time_string):
        hours, minutes, seconds = (time_string or '0:0:0').split(':')
        return int(hours) * 60 + int(minutes) + float(seconds) / 60

    bar = ProgressBar('Fetching', count=7, max_len=28 + len(contest_id))

    contest = req('')
    freeze_duration = time_string_to_minutes(contest['scoreboard_freeze_duration'])
    contest_duration = time_string_to_minutes(contest['duration'])
    bins = 120
    scale = contest_duration / bins

    problems = req_assoc('problems')
    submissions = req_assoc('submissions')
    teams = req_assoc(f'teams?public=1')
    languages = req_assoc('languages')
    judgement_types = req_assoc('judgement-types')
    judgement_types[''] = {'id': '', 'name': 'pending'}
    judgement_colors = {'AC': 'lime', 'WA': 'red', 'TLE': '#c0f', 'RTE': 'orange', '': 'skyblue'}

    for j in req('judgements'):
        # Firstly, only one judgement should be 'valid': in case of rejudgings, this should be the "active" judgement.
        # Secondly, note that the submissions list only contains submissions that were submitted on time,
        # while the judgements list contains all judgements, therefore the submission might not exist.
        if j['valid'] and j['submission_id'] in submissions:
            # Add judgement to submission.
            submissions[j['submission_id']]['judgement'] = j

    bar.finalize()

    ac_teams = {p: set() for p in problems}
    stats = {p: [{j: 0 for j in judgement_types} for _ in range(bins)] for p in problems}
    stats_sum = {p: {j: 0 for j in judgement_types} for p in problems}
    language_stats = {l: {j: 0 for j in judgement_types} for l in languages}

    for i, s in submissions.items():
        if s['team_id'] not in teams:
            continue
        minute = time_string_to_minutes(s['contest_time'])
        if 0 <= minute < contest_duration:
            jt = (
                ''
                if not post_freeze and minute >= contest_duration - freeze_duration
                else s['judgement']['judgement_type_id']
            )
            if jt is None:
                continue
            if jt == 'AC':
                ac_teams[s['problem_id']].add(s['team_id'])
            stats[s['problem_id']][int(minute / scale)][jt] += 1 if jt in ['AC', ''] else -1
            stats_sum[s['problem_id']][jt] += 1
            language_stats[s['language_id']][jt] += 1

    problem_stats = ''

    bar = ProgressBar('Plotting', items=[*stats.keys(), 'Language Stats'])

    makedirs(f'solve_stats/activity', exist_ok=True)
    for p, minutes in stats.items():
        bar.start(p)
        label = problems[p]['label']
        fig, ax = plt.subplots(figsize=(12, 2))
        # Ugly accumulator. Matplotlib doesn't support negative stacked bars properly: https://stackoverflow.com/a/38900035
        neg_acc = [0 for m in minutes]
        # Reverse order, so that the order at the bottom is WA-TLE-RTE
        for jt in sorted(judgement_types, reverse=True):
            if jt == 'CE':
                continue
            is_neg = any(m[jt] < 0 for m in minutes)
            ax.bar(
                range(bins),
                [m[jt] for m in minutes],
                1,
                color=judgement_colors.get(jt) or judgement_colors['RTE'],
                bottom=neg_acc if is_neg else None,
            )
            if is_neg:
                neg_acc = [a + b for a, b in zip(neg_acc, (m[jt] for m in minutes))]
        plt.axhline(y=0, linewidth=1, color='gray')
        ax.autoscale(enable=True, axis='both', tight=True)
        fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
        plt.axis('off')
        plt.tight_layout(pad=0)
        plt.savefig(f'solve_stats/activity/{label}.pdf', bbox_inches='tight', transparent=True)

        problem_stats += (
            r'\providecommand{\solvestats'
            + label
            + r'}{\printsolvestats{'
            + '}{'.join(
                str(x) for x in [sum(stats_sum[p].values()), len(ac_teams[p]), stats_sum[p]['']]
            )
            + '}}\n'
        )
        bar.done()

    Path('solve_stats/problem_stats.tex').write_text(problem_stats)

    bar.start('Language Stats')
    fig, ax = plt.subplots(figsize=(8, 4))
    for j, (jt, color) in enumerate(judgement_colors.items()):
        ax.bar(
            [i + (j - 2) * 0.15 for i in range(len(languages))],
            [language_stats[l][jt] for l in languages],
            0.15,
            label=judgement_types[jt]['name'],
            color=color,
        )
    ax.set_xticks(range(len(languages)), [l['name'] for l in languages.values()])
    ax.legend()
    fig.tight_layout()
    plt.savefig(f'solve_stats/language_stats.pdf', bbox_inches='tight', transparent=True)
    bar.done()

    bar.finalize()
