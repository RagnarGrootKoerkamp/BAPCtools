#!/usr/bin/env python3

# Reads a local submissions.json and judgements.json.
# Searches for all submissions of a given language and prints+plots the timings for
# those that were AC originally and on the latest rejudge.

import json
from pathlib import Path

import matplotlib.pyplot as plt


def read_json(path):
    return json.loads(Path(path).read_text())


submissions = read_json("submissions.json")
judgements = read_json("judgements.json")


# For each |lang| submission find the first and last judgement.
# If both are AC, return the old and new max_time.
def get_times(lang):
    # (from, to)
    points = []
    for s in submissions:
        if s["language_id"] != lang:
            continue
        js = [j for j in judgements if j["submission_id"] == s["id"]]
        assert len(js) > 1
        if js[0]["judgement_type_id"] == "AC" and js[-1]["judgement_type_id"] == "AC":
            points.append((js[0]["max_run_time"], js[-1]["max_run_time"]))

    return points


def print_scatter_plot(points):
    fig, ax = plt.subplots()
    ax.scatter([p[0] for p in points], [p[1] for p in points], s=1, c=[[0, 0, 0]])
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.plot([0, 1, 2, 3])
    fig.tight_layout()
    plt.show()


times = get_times("python3")
times.sort()
print(times)
print_scatter_plot(times)
