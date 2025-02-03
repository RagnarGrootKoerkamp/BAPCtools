#!/usr/bin/env python3

# Converts a problem.en.tex to problem.en.md and creates a gitlab issue from it.
# Note: This uses Pandoc and requires the file ~/.pandoc/filters/gitlab-math.lua containing:
#
# function Math(el)
#     if el.mathtype == "InlineMath" then
#         return {pandoc.RawInline('html','$`' .. el.text .. '`$')}
# 	  else
# 		  return {pandoc.RawInline('html','```math\n' .. el.text .. '\n```')}
#     end
# end

import requests
import argparse
import tempfile
import subprocess
import sys
from pathlib import Path

# Replace the upper case parts.
URL = "https://GITLAB_INSTANCE/api/v4/projects/PROJECT_ID/issues"
API_KEY = "SECRET_KEY"

headers = {"PRIVATE-TOKEN": API_KEY}

scriptdir = Path(sys.argv[0]).parent


def process_problem(path):
    name = path.name
    mdpath = path / "problem_statement" / "problem.en.md"

    tmppath = None
    if not mdpath.is_file():
        tex = path / "problem_statement" / "problem.en.tex"
        if not tex.is_file():
            return
        tmpfile, tmppath = tempfile.mkstemp()

        subprocess.run(
            [
                "pandoc",
                "-flatex",
                scriptdir / "header.tex",
                tex,
                "-tgfm",
                "--lua-filter=gitlab-math.lua",
            ],
            stdout=tmpfile,
        )
        mdpath = Path(tmppath)

    response = requests.post(
        URL,
        headers=headers,
        data={"labels": "CFP", "title": name, "description": mdpath.read_text()},
    )
    print(response.text)
    if tmppath:
        Path(tmppath).unlink()


parser = argparse.ArgumentParser()
parser.add_argument("problem", nargs="+")
for problem in parser.parse_args().problem:
    process_problem(Path(problem))
