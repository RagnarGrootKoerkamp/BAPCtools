#!/usr/bin/env bash
set -euo pipefail

USER=Ragnar
PASS=$(pass dj.storm.vu | head -1)
URL=https://dj.storm.vu
CID=4

dir=$(mktemp -d)
for endpoint in teams organizations problems scoreboard; do
    curl -u "$USER:$PASS" $URL/api/v4/contests/$CID/$endpoint >$dir/$endpoint
done

rm -f scoreboard.zip
zip -j scoreboard.zip $dir/*

echo Wrote scoreboard.zip
