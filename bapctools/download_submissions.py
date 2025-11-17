#!/usr/bin/env python3
import base64
import json
from os import makedirs
from pathlib import Path
from typing import Any

from bapctools import config, parallel
from bapctools.contest import call_api_get_json, get_contest_id
from bapctools.util import fatal, ProgressBar
from bapctools.verdicts import from_string, Verdict

# Example usage:
# bt download_submissions [--user <username>] [--password <password>] [--contest <contest_id>] [--api <domjudge_url>]


def download_submissions() -> None:
    contest_id = get_contest_id()
    if contest_id is None:
        fatal("No contest ID found. Set in contest.yaml or pass --contest-id <cid>.")

    for d in ["submissions", "scoreboard"]:
        Path(d).mkdir(exist_ok=True)

    bar = ProgressBar("Downloading metadata", count=3, max_len=len("submissions"))
    bar.start("submissions")
    submissions = {s["id"]: s for s in call_api_get_json(f"/contests/{contest_id}/submissions")}
    bar.done()

    submission_digits = max(len(s["id"]) for s in submissions.values())
    team_digits = max(
        len(s["team_id"]) if s["team_id"].isdigit() else 0 for s in submissions.values()
    )

    bar.start("scoreboard")
    for endpoint in ["teams", "organizations", "problems", "scoreboard", "clarifications"]:
        with open(f"scoreboard/{endpoint}.json", "w") as f:
            f.write(json.dumps(call_api_get_json(f"/contests/{contest_id}/{endpoint}"), indent=2))
    bar.done()

    bar.start("judgements")
    for j in call_api_get_json(f"/contests/{contest_id}/judgements"):
        # Note that the submissions list only contains submissions that were submitted on time,
        # while the judgements list contains all judgements, therefore the submission might not exist.
        if j["submission_id"] in submissions:
            # Merge judgement with submission. Keys of judgement are overwritten by keys of submission.
            submissions[j["submission_id"]] = {**j, **submissions[j["submission_id"]]}
    bar.done()
    bar.finalize()

    bar = ProgressBar("Downloading sources", count=len(submissions), max_len=4)

    def download_submission(s: dict[str, Any]) -> None:
        i = int(s["id"])
        bar.start(s["id"])
        if "judgement_type_id" not in s:
            bar.done()
            return

        verdict = from_string(s["judgement_type_id"])
        verdict_dir = {
            Verdict.ACCEPTED: "accepted",
            Verdict.WRONG_ANSWER: "wrong_answer",
            Verdict.TIME_LIMIT_EXCEEDED: "time_limit_exceeded",
            Verdict.RUNTIME_ERROR: "run_time_error",
            Verdict.VALIDATOR_CRASH: "validator_crash",
            Verdict.COMPILER_ERROR: "compiler_error",
        }[verdict]

        source_code = call_api_get_json(f"/contests/{contest_id}/submissions/{i}/source-code")
        if len(source_code) != 1:
            bar.warn(
                f"\nSkipping submission {i}: has {len(source_code)} source files instead of 1."
            )
            bar.done()
            return
        source: bytes = base64.b64decode(source_code[0]["source"])
        makedirs(f"submissions/{s['problem_id']}/{verdict_dir}", exist_ok=True)
        teamid = f"{s['team_id']:>0{team_digits}}" if s["team_id"].isdigit() else s["team_id"]
        submissionid = f"{i:>0{submission_digits}}"
        ext = source_code[0]["filename"].split(".")[-1]
        with open(
            f"submissions/{s['problem_id']}/{verdict_dir}/t{teamid}_s{submissionid}_{s['max_run_time']}s.{ext}",
            "wb",
        ) as f:
            f.write(source)
        bar.done()

    # When downloading submissions, we need to wait for the server to respond, so we can use more jobs
    config.args.jobs *= 10
    parallel.run_tasks(download_submission, list(submissions.values()))

    bar.finalize()
