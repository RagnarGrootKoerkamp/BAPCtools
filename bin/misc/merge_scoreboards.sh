#!/usr/bin/env sh
#
# Merge scoreboards using the DOMjudge socreboard:merge tool.
# Run `sudo docker-compose up` in the domjudge git repo before running this script.

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

sudo docker-compose exec domjudge sudo -u domjudge webapp/bin/console scoreboard:merge merged.zip 'BAPC Preliminaries 2022' \
    https://{user}:{pass}@www.domjudge.org/demoweb/api/v4/contests/{cid} {group_id} \
    {some_other_url}/api/v4/contests/{cid} {group_id}
