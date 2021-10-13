#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
    echo Pass the url to the contest, optionally including username and password:
    echo 'https://{USER}:{PASSWORD}@{URL}/api/contests/{CONTEST_ID}'
    echo Example: https://www.domjudge.org/demoweb/api/contests/1
    exit 1
fi

# URL = https://{USER}:{PASSWORD}@{URL}/api/contests/{CONTEST_ID}
# URL = https://domjudge.org/demoweb/api/contests/1
URL=$1

dir=$(mktemp -d)
for endpoint in teams organizations problems scoreboard; do
    curl -L $URL/$endpoint >$dir/$endpoint
done

rm -f scoreboard.zip
zip -j scoreboard.zip $dir/*

echo Wrote scoreboard.zip
