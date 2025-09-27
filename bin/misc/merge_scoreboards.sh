#!/bin/sh
#
# Merge scoreboards using the DOMjudge socreboard:merge tool.
# Run `sudo docker-compose up` in the domjudge git repo before running this script.
#
# NOTE: This requires `/home/path/to/scoreboards:/scoreboards` added to volumes
# in `docker-compose.yaml` in the domjudge repo.

# The best way of using this script is to just copy it and update/add arguments as needed.
#
# The arguments alternate contest ids and the group ids to include.
# Contest ids can be found from `/api/v4/contests`.
# Group ids can be found from `/api/v4/contests/<id>/groups`, or by selecting
# them using the filter at the top of the `/public` scoreboard page.
# URLs should have the form https://<domain>/api/v4/contests/<contestid>/.
# If a URL requires authentication, add username:password@ after the https://.
# Only the /teams, /organizations, /problems and /scoreboard endpoint are used,
# so manually putting files in those locations can work as well.
#
# Steps:
# 1. Get the public url, ie https://judge.gehack.nl
# 2. Change to API address: https://judge.gehack.nl/api/v4
# 3. Add username and (url-encoded) password: https://username:password@judge.gehack.nl/api/v4
# 4. Find contest id in:
#      curl https://username:password@judge.gehack.nl/api/v4/contests | jq
# 5. Find group id in:
#      curl https://username:password@judge.gehack.nl/api/v4/contests/<contestid>/groups | jq
# 6. Add to the call below:
#      https://username:password@judge.gehack.nl/api/v4/contests/<contestid> <groupid> \
# 7. Repeat
# 8. cd to domjudge repository (use github.com/ragnargrootkoerkamp/domjudge branch 'scoreboardmerge') and run this script from there:
#    cd ~/git/domjudge
#    sudo systemctl start docker
#    sudo docker-compose rm -f   # in case of errors
#    sudo docker-compose pull    # in case of errors
#    sudo docker-compose up
#    ./merge_scoreboards.sh
#    ~/git/bapc/2023/prelims/merge_scoreboards.sh
#
# 9. Afterwards, download contests using the BAPCtools/bin/misc/download_scoreboard.py script.
#
# Examples:
# - public scoreboard:
#    https://judge.gehack.nl/api/v4/contests/2 3 \
# - private scoreboard:
#    https://username:password@judge.gehack.nl/api/v4/contests/eapc participants \
#
# - local scoreboard:
#   /scoreboards/eindhoven participants \
#   NOTE: This needs to be mounted in the docker-compose.yaml file:
#   volumes:
#     - /home/path/to/scoreboards:/scoreboards
#
# To run in a loop locally:
# while true; ./merge_scoreboards.sh ; sleep 60 ; end

# DOWNLOAD SCOREBOARDS
echo Downloading..
# TODO: UPDATE TO PATH TO download_scoreboard.sh
download=~/git/bapc/bapctools/bin/misc/download_scoreboard.sh
# TODO: ADD MORE SITES
$download https://scoreboard:password@judge.gehack.nl/api/v4/contests/eapc2023 eindhoven.zip

# EXTRACT
for f in *.zip; do
    unzip -o $f -d $(basename $f .zip)
done

cwd=$(pwd)

# TODO: UPDATE TO PATH TO DOMJUDGE REPO
cd ~/git/domjudge

echo Merging..
# MERGE
# TODO: UPDATE CONTEST NAMES AND GROUP NUMBERS
docker-compose exec domjudge sudo -u domjudge webapp/bin/console scoreboard:merge \
    /scoreboards/merged.zip 'BAPC Preliminaries 2023' \
    /scoreboards/delft contestants \
    /scoreboards/eindhoven 32365

cd $cwd

# TODO UPDATE SERVER PATH
# echo Rsync to server..
# rsync -r merged/ server:/path/to/server
echo Done!
