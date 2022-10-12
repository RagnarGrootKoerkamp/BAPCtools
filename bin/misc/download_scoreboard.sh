#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
    echo Pass the url to the contest, optionally including username and password, and optionally the name of the zip to write:
    echo 'https://{USER}:{PASSWORD}@{URL}/api/contests/{CONTEST_ID}'
    echo Example: "https://www.domjudge.org/demoweb/api/contests/1 scoreboard.zip"
    exit 1
fi

# URL = https://{USER}:{PASSWORD}@{URL}/api/contests/{CONTEST_ID}
# URL = https://domjudge.org/demoweb/api/contests/1
URL="$1"

dir="$(mktemp -d)"
for endpoint in teams organizations problems scoreboard; do
    curl --fail --location "$URL/$endpoint" >"$dir/$endpoint.json"
done

OUT=scoreboard.zip

if [ $# -eq 2 ]; then
    OUT="$2"
fi

zip -j "$OUT" "$dir"/*

echo "Wrote $OUT"
