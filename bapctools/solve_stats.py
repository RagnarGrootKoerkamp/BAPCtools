from multiprocessing import Pool
from os import makedirs
from pathlib import Path
from typing import Any, Optional

from bapctools import config, parallel
from bapctools.contest import call_api_get_json, get_contest_id
from bapctools.util import ProgressBar

# Note on multiprocessing:
# Our custom parallel module uses light-weight threads, which all compete for the global interpreter lock:
# https://docs.python.org/3.10/glossary.html#term-global-interpreter-lock
# But matplotlib.pyplot almost exclusively uses the interpreter, so light-weight threads would simply
# wait on each other until they can obtain the lock.
# Instead, multiprocessing spawns full-fledged Python processes and pickles the arguments and return values.
# This means we cannot use closures or share global data, e.g. we cannot share `bar` instance between the processes.
# Our custom parallel module can be used for API fetching without problems.

bins = 120
judgement_colors = {"AC": "lime", "WA": "red", "TLE": "#c0f", "RTE": "orange", "": "skyblue"}


# Turns an endpoint list result into an object, mapped by 'id'
def get_json_assoc(url: str) -> dict[str, dict[str, Any]]:
    return {o["id"]: o for o in call_api_get_json(url)}


def time_string_to_minutes(time_string: str) -> float:
    hours, minutes, seconds = (time_string or "0:0:0").split(":")
    return int(hours) * 60 + int(minutes) + float(seconds) / 60


def plot_problem(
    minutes: list[dict[str, int]],
    label: str,
    judgement_types: dict[str, dict[str, Any]],
) -> None:
    import matplotlib.pyplot as plt  # Have to import it separately in multiprocessing worker.

    fig, ax = plt.subplots(figsize=(12, 2))
    # Ugly accumulator. Matplotlib doesn't support negative stacked bars properly: https://stackoverflow.com/a/38900035
    neg_acc = [0 for _ in minutes]
    # Reverse order, so that the order at the bottom is WA-TLE-RTE
    for jt in sorted(judgement_types, reverse=True):
        if jt == "CE":
            continue
        is_neg = any(m[jt] < 0 for m in minutes)
        ax.bar(
            range(bins),
            [m[jt] for m in minutes],
            1,
            color=judgement_colors.get(jt) or judgement_colors["RTE"],
            bottom=neg_acc if is_neg else None,
        )
        if is_neg:
            neg_acc = [a + b for a, b in zip(neg_acc, (m[jt] for m in minutes))]
    ax.axhline(y=0, linewidth=1, color="gray")
    ax.autoscale(enable=True, axis="both", tight=True)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.axis("off")
    fig.tight_layout(pad=0)
    fig.savefig(f"solve_stats/activity/{label}.pdf", bbox_inches="tight", transparent=True)


def generate_solve_stats(post_freeze: bool) -> None:
    # Import takes more than 1000 ms to evaluate, so only import inside function (when it is actually needed)
    import matplotlib
    import matplotlib.pyplot as plt

    # Default back-end uses Qt, which cannot run in parallel threads
    # See: https://github.com/matplotlib/matplotlib/issues/13296
    matplotlib.use("pdf")

    num_jobs = max(1, config.args.jobs)

    contest_id = get_contest_id()
    url_prefix = f"/contests/{contest_id}/"

    bar = ProgressBar("Fetching", count=3, max_len=len("Contest data"))

    bar.start("Contest")
    contest = call_api_get_json(url_prefix)
    bar.done()

    freeze_duration = time_string_to_minutes(contest["scoreboard_freeze_duration"])
    contest_duration = time_string_to_minutes(contest["duration"])
    scale = contest_duration / bins

    def get_contest_data(i_endpoint: tuple[int, str]) -> None:
        i, endpoint = i_endpoint
        data[i] = get_json_assoc(url_prefix + endpoint)

    bar.start("Contest data")
    data: list[Optional[dict[str, Any]]] = [None] * 5
    parallel.run_tasks(
        get_contest_data,
        list(
            enumerate(["problems", "submissions", "teams?public=1", "languages", "judgement-types"])
        ),
    )
    problems, submissions, teams, languages, judgement_types = data
    assert problems is not None, "Could not fetch problems"
    assert submissions is not None, "Could not fetch submissions"
    assert teams is not None, "Could not fetch teams"
    assert languages is not None, "Could not fetch languages"
    assert judgement_types is not None, "Could not fetch judgement_types"
    bar.done()

    judgement_types[""] = {"id": "", "name": "pending"}

    bar.start("Judgements")
    for j in call_api_get_json(url_prefix + "judgements"):
        # Firstly, only one judgement should be 'valid': in case of rejudgings, this should be the "active" judgement.
        # Secondly, note that the submissions list only contains submissions that were submitted on time,
        # while the judgements list contains all judgements, therefore the submission might not exist.
        if j["valid"] and j["submission_id"] in submissions:
            # Add judgement to submission.
            submissions[j["submission_id"]]["judgement"] = j
    bar.done()

    bar.finalize()

    ac_teams: dict[str, set[str]] = {p: set() for p in problems}
    stats = {p: [{j: 0 for j in judgement_types} for _ in range(bins)] for p in problems}
    stats_sum = {p: {j: 0 for j in judgement_types} for p in problems}
    language_stats = {lang: {j: 0 for j in judgement_types} for lang in languages}

    for s in submissions.values():
        if s["team_id"] not in teams:
            continue
        minute = time_string_to_minutes(s["contest_time"])
        if 0 <= minute < contest_duration:
            jt = (
                ""
                if not post_freeze and minute >= contest_duration - freeze_duration
                else s["judgement"]["judgement_type_id"]
            )
            if jt is None:
                continue
            if jt == "AC":
                ac_teams[s["problem_id"]].add(s["team_id"])
            stats[s["problem_id"]][int(minute / scale)][jt] += 1 if jt in ["AC", ""] else -1
            stats_sum[s["problem_id"]][jt] += 1
            language_stats[s["language_id"]][jt] += 1

    problem_stats = dict[str, str]()

    bar = ProgressBar("Plotting", items=["Problem activity", "Language stats"])
    makedirs("solve_stats/activity", exist_ok=True)

    bar.start("Problem activity")
    with Pool(num_jobs) as p:
        p.starmap(
            plot_problem,
            [
                # Passing all required data to plot_problem, because we dan't use closures (see comment at top of file)
                [stats[problem_id], problems[problem_id]["label"], judgement_types]
                for problem_id in stats
            ],
        )
    bar.done()

    for problem_id in stats:
        problem_stats[problem_id] = (
            r"\providecommand{\solvestats"
            + problems[problem_id]["label"]
            + r"}{\printsolvestats{"
            + "}{".join(
                str(x)
                for x in [
                    sum(stats_sum[problem_id].values()),
                    len(ac_teams[problem_id]),
                    stats_sum[problem_id][""],
                ]
            )
            + "}}\n"
        )

    Path("solve_stats/problem_stats.tex").write_text(
        "".join(problem_stats[p] for p in sorted(problem_stats.keys()))
    )

    bar.start("Language stats")
    fig, ax = plt.subplots(figsize=(8, 4))
    for j, (jt, color) in enumerate(judgement_colors.items()):
        ax.bar(
            [i + (j - 2) * 0.15 for i in range(len(languages))],
            [language_stats[lang][jt] for lang in languages],
            0.15,
            label=judgement_types[jt]["name"],
            color=color,
        )
    ax.set_xticks(range(len(languages)), [lang["name"] for lang in languages.values()])
    ax.legend()
    fig.tight_layout()
    fig.savefig("solve_stats/language_stats.pdf", bbox_inches="tight", transparent=True)
    bar.done()

    bar.finalize()
