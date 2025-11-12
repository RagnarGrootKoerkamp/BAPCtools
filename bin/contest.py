import datetime
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Optional, TYPE_CHECKING

import config
from util import (
    error,
    fatal,
    has_ryaml,
    log,
    read_yaml,
    read_yaml_settings,
    verbose,
    warn,
    YamlParser,
)

if TYPE_CHECKING:
    import requests


class ContestYaml:
    def __init__(self, yaml_data: Optional[dict[object, object]]) -> None:
        self.exists = yaml_data is not None
        parser = YamlParser("contest.yaml", yaml_data or {})

        # known keys
        self.api: Optional[str] = parser.extract_optional("api", str)
        self.contest_id: Optional[str] = parser.extract_optional("contest_id", str)
        parser.extract_deprecated("print_timelimit", "print_time_limit")
        self.print_time_limit: Optional[bool] = parser.extract_optional("print_time_limit", bool)
        self.test_session: bool = parser.extract("test_session", False)
        self.order: Optional[str] = parser.extract_optional("order", str)
        self.start_time: Optional[str] = None
        start_time = parser.extract_optional("start_time", datetime.date)
        if start_time is not None:
            self.start_time = start_time.isoformat()
            if "+" not in self.start_time:
                self.start_time += "+00:00"

        # contains remaining proper keys
        self._yaml = {k: v for k, v in parser.yaml.items() if isinstance(k, str) and v is not None}
        for key in parser.yaml:
            if key not in self._yaml:
                warn(f"invalid contest.yaml key: {key} in root")

    def dict(self) -> dict[str, object]:
        data = {k: v for k, v in vars(self).items() if not k.startswith("_") and v is not None}
        data.update(self._yaml)
        if not has_ryaml:
            for key in ("duration", "scoreboard_freeze_duration"):
                if key in data:
                    # YAML 1.1 parses 1:00:00 as 3600. Convert it back to a string if so.
                    # (YAML 1.2 and ruamel.yaml parse it as a string.)
                    if isinstance(data[key], int):
                        data[key] = str(datetime.timedelta(seconds=data[key]))
        return data


# Read the contest.yaml, if available
_contest_yaml: Optional[ContestYaml] = None


def contest_yaml() -> ContestYaml:
    global _contest_yaml
    if _contest_yaml is not None:
        return _contest_yaml

    raw_contest_yaml = None
    contest_yaml_path = Path("contest.yaml")
    if contest_yaml_path.is_file():
        raw_contest_yaml = read_yaml_settings(contest_yaml_path)
    if raw_contest_yaml is not None and not isinstance(raw_contest_yaml, dict):
        fatal("could not parse contest.yaml.")

    _contest_yaml = ContestYaml(raw_contest_yaml)
    return _contest_yaml


_problems_yaml: Literal[False] | Optional[Sequence[Mapping[str, Any]]] = None


def problems_yaml() -> Optional[Sequence[Mapping[str, Any]]]:
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
    return _problems_yaml


def get_api() -> str:
    api = config.args.api or contest_yaml().api
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
    contest_id = config.args.contest_id if config.args.contest_id else contest_yaml().contest_id
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
        error(f"\nError in decoding JSON:\n{e}\n{r.text}")
