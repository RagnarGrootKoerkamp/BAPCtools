#!/usr/bin/env python3
import base64
import json
from os import makedirs

import config
import parallel
from contest import call_api, get_contest_id
from util import ProgressBar, fatal
from verdicts import Verdict, from_string


# Example usage:
# bt download_submissions [--user <username>] [--password <password>] [--contest <contest_id>] [--api <domjudge_url>]


def req(url: str):
    r = call_api('GET', url)
    r.raise_for_status()
    try:
        return r.json()
    except Exception as e:
        fatal(f'\nError in decoding JSON:\n{e}\n{r.text()}')


def download_submissions():
    contest_id = get_contest_id()
    if contest_id is None:
        fatal("No contest ID found. Set in contest.yaml or pass --contest-id <cid>.")

    bar = ProgressBar('Downloading metadata', count=4, max_len=len('submissions'))
    bar.start('submissions')
    submissions = {s["id"]: s for s in req(f"/contests/{contest_id}/submissions")}
    bar.done()

    submission_digits = max(len(s['id']) for s in submissions.values())
    team_digits = max(
        len(s['team_id']) if s['team_id'].isdigit() else 0 for s in submissions.values()
    )

    bar.start('teams')
    with open(f"submissions/teams.json", "w") as f:
        f.write(json.dumps(call_api_get_json(f"/contests/{contest_id}/teams"), indent=2))
    bar.done()

    # Fetch account info so we can filter for team submissions
    bar.start('accounts')
    accounts = {a['team_id']: a for a in req(f"/contests/{contest_id}/accounts")}
    bar.done()

    bar.start('judgements')
    for j in req(f"/contests/{contest_id}/judgements"):
        # Note that the submissions list only contains submissions that were submitted on time,
        # while the judgements list contains all judgements, therefore the submission might not exist.
        if j["submission_id"] in submissions:
            # Merge judgement with submission. Keys of judgement are overwritten by keys of submission.
            submissions[j["submission_id"]] = {**j, **submissions[j["submission_id"]]}
    bar.done()
    bar.finalize()

    bar = ProgressBar('Downloading sources', count=len(submissions), max_len=4)

    def download_submission(s):
        i = int(s["id"])
        bar.start(s["id"])
        if "judgement_type_id" not in s:
            bar.done()
            return
        if accounts[s["team_id"]]["type"] != "team":
            bar.done()
            return

        verdict = from_string(s["judgement_type_id"])
        verdict_dir = {
            Verdict.ACCEPTED: 'accepted',
            Verdict.WRONG_ANSWER: 'wrong_answer',
            Verdict.TIME_LIMIT_EXCEEDED: 'time_limit_exceeded',
            Verdict.RUNTIME_ERROR: 'run_time_error',
            Verdict.VALIDATOR_CRASH: 'validator_crash',
            Verdict.COMPILER_ERROR: 'compiler_error',
        }[verdict]

        source_code = req(f"/contests/{contest_id}/submissions/{i}/source-code")
        if len(source_code) != 1:
            bar.warn(
                f"\nSkipping submission {i}: has {len(source_code)} source files instead of 1."
            )
            bar.done()
            return
        source: bytes = base64.b64decode(source_code[0]["source"])
        makedirs(f"submissions/{s['problem_id']}/{verdict_dir}", exist_ok=True)
        teamid = f"{s['team_id']:>0{team_digits}}" if s['team_id'].isdigit() else s['team_id']
        submissionid = f"{i:>0{submission_digits}}"
        ext = source_code[0]['filename'].split('.')[-1]
        with open(
            f"submissions/{s['problem_id']}/{verdict_dir}/t{teamid}_s{submissionid}.{ext}",
            "wb",
        ) as f:
            f.write(source)
        bar.done()

    # When downloading submissions, we need to wait for the server to respond, so we can use more jobs
    config.args.jobs *= 10
    parallel.run_tasks(download_submission, list(submissions.values()))

    bar.finalize()
