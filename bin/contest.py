import config
import sys

from pathlib import Path
from typing import cast, Any, Optional, TYPE_CHECKING

from util import error, fatal, log, read_yaml, read_yaml_settings, verbose

if TYPE_CHECKING:
    import requests

# Read the contest.yaml, if available
_contest_yaml: Optional[dict[str, Any]] = None


def contest_yaml() -> dict[str, Any]:
    global _contest_yaml
    if _contest_yaml is not None:
        return _contest_yaml

    contest_yaml_path = Path("contest.yaml")
    if contest_yaml_path.is_file():
        _contest_yaml = read_yaml_settings(contest_yaml_path)
        return _contest_yaml
    _contest_yaml = {}
    return _contest_yaml


_problems_yaml = None


def problems_yaml() -> Optional[list[dict[str, Any]]]:
    global _problems_yaml
    if _problems_yaml is False:
        return None
    if _problems_yaml:
        return _problems_yaml

    problemsyaml_path = Path("problems.yaml")
    if not problemsyaml_path.is_file():
        _problems_yaml = False
        return None
    _problems_yaml = read_yaml(problemsyaml_path)
    if _problems_yaml is None:
        _problems_yaml = False
        return None
    if not isinstance(_problems_yaml, list):
        fatal("problems.yaml must contain a list of problems")
    return cast(list[dict[str, Any]], _problems_yaml)


def get_api() -> str:
    api = config.args.api or cast(str, contest_yaml().get("api"))
    if not api:
        fatal(
            "Could not find key `api` in contest.yaml and it was not specified on the command line."
        )
    if api.endswith("/"):
        api = api[:-1]
    if not api.endswith("/api/v4"):
        api += "/api/v4"
    return api


def get_contest_id() -> str:
    contest_id = (
        config.args.contest_id
        if config.args.contest_id
        else contest_yaml()["contest_id"]
        if "contest_id" in contest_yaml()
        else None
    )
    contests = get_contests()
    if contest_id is not None:
        if contest_id not in {c["id"] for c in contests}:
            for contest in contests:
                log(f"{contest['id']}: {contest['name']}")
            fatal(f"Contest {contest_id} not found.")
        else:
            return contest_id
    if not contests:
        fatal("Server has no active contests.")
    elif len(contests) > 1:
        for contest in contests:
            log(f"{contest['id']}: {contest['name']}")
        fatal(
            "Server has multiple active contests. Pass --contest-id <cid> or set it in contest.yaml."
        )
    else:
        assert len(contests) == 1
        assert isinstance(contests[0]["id"], str)
        log(f"The only active contest has id {contests[0]['id']}")
        return contests[0]["id"]


def get_contests() -> list[dict[str, Any]]:
    contests = call_api_get_json("/contests")
    assert isinstance(contests, list)
    return contests


def call_api(method: str, endpoint: str, **kwargs: Any) -> "requests.Response":
    if config.args.username is None or config.args.password is None:
        fatal("Username and Password are required to access CCS")

    import requests  # Slow import, so only import it inside this function.

    assert endpoint.startswith("/")
    url = get_api() + endpoint
    verbose(f"{method} {url}")
    r = requests.request(
        method,
        url,
        auth=requests.auth.HTTPBasicAuth(config.args.username, config.args.password),
        **kwargs,
    )

    if not r.ok:
        error(r.text)
    return r


def call_api_get_json(url: str) -> Any:
    r = call_api("GET", url)
    r.raise_for_status()
    try:
        return r.json()
    except Exception as e:
        print(f"\nError in decoding JSON:\n{e}\n{r.text}", file=sys.stderr)
