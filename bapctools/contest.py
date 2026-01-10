import datetime
import string
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from bapctools import config
from bapctools.util import (
    error,
    fatal,
    log,
    read_yaml,
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
            if not isinstance(key, str):
                warn(f"invalid contest.yaml key: {key} in root")

    def dict(self) -> dict[str, object]:
        data = {k: v for k, v in vars(self).items() if not k.startswith("_") and v is not None}
        data.update(self._yaml)
        return data


class ProblemsYamlEntry:
    def __init__(self, yaml_data: dict[object, object], index: int) -> None:
        self.ok = False
        parser = YamlParser("problems.yaml", yaml_data)

        def get_hex(rgb: Optional[str]) -> Optional[str]:
            if rgb is None:
                return None
            if not rgb.startswith("#"):
                error(
                    f"invalid rgb value '{rgb}' for problem {index} (id: {self.id}) in problems.yaml. SKIPPED"
                )
                return None
            hex_part = rgb[1:].lower()
            if len(hex_part) == 3:
                hex_part = "".join(c * 2 for c in hex_part)
            if len(hex_part) != 6 or any(c not in string.hexdigits for c in hex_part):
                error(
                    f"invalid rgb value '{rgb}' for problem {index} (id: {self.id}) in problems.yaml. SKIPPED"
                )
                return None
            return hex_part

        # known keys
        self.id: str = parser.extract_and_error("id", str)
        self.label: str = parser.extract_and_error("label", str)
        self.rgb: Optional[str] = get_hex(parser.extract_optional("rgb", str))

        # unused keys
        if isinstance(parser.yaml.get("name", None), str):
            parser.yaml["name"] = {"en": parser.yaml["name"]}
        names: dict[object, object] = parser.extract("name", {"en": ""})
        self.name: dict[str, str] = {}
        for lang, name in names.items():
            if not isinstance(lang, str):
                warn(
                    f"invalid language '{lang}' for problem {index} (id: {self.id}) in problems.yaml. SKIPPED."
                )
            elif not isinstance(name, str):
                warn(
                    f"incompatible value for language '{lang}' for problem {index} (id: {self.id}) in problems.yaml. SKIPPED."
                )
            else:
                self.name[lang] = name
        self.time_limit: Optional[float] = parser.extract_optional("time_limit", float)
        if self.time_limit is not None and not self.time_limit > 0:
            error(
                f"value for 'time_limit' for problem {index} (id: {self.id}) in problems.yaml should be > 0 but is {self.time_limit}. SKIPPED"
            )
            self.time_limit = None

        # contains remaining proper keys
        self._yaml = {k: v for k, v in parser.yaml.items() if isinstance(k, str) and v is not None}
        for key in parser.yaml:
            if key not in self._yaml:
                warn(f"invalid problems.yaml key: {key} for problem {index} (id: {self.id})")

        self.ok = parser.errors == 0


# cache the contest.yaml and problems.yaml
_contest_yaml: Optional[ContestYaml] = None
_problems_yaml: Optional[Sequence[ProblemsYamlEntry]] = None


def contest_yaml() -> ContestYaml:
    global _contest_yaml
    if _contest_yaml is not None:
        return _contest_yaml

    contest_yaml_path = Path("contest.yaml")
    if contest_yaml_path.is_file():
        raw_yaml = read_yaml(contest_yaml_path)
        if not isinstance(raw_yaml, dict):
            fatal("could not parse contest.yaml, must be a dict.")
    else:
        raw_yaml = None

    _contest_yaml = ContestYaml(raw_yaml)
    return _contest_yaml


def problems_yaml() -> Sequence[ProblemsYamlEntry]:
    global _problems_yaml
    if _problems_yaml is not None:
        return _problems_yaml

    problems_yaml_path = Path("problems.yaml")
    raw_yaml: object = []
    if problems_yaml_path.is_file():
        raw_yaml = read_yaml(problems_yaml_path)
    if not isinstance(raw_yaml, list):
        fatal("could not parse problems.yaml, must be a list.")

    problems = []
    labels: dict[str, str] = {}
    for i, yaml_data in enumerate(raw_yaml):
        if not isinstance(yaml_data, dict):
            error("entries in problems.yaml must be dicts.")
            continue
        problem = ProblemsYamlEntry(yaml_data, i)
        if not problem.ok:
            continue
        if problem.label in labels:
            error(f"label {problem.label} found twice in problems.yaml")
            continue
        labels[problem.label] = problem.id
        if not Path(problem.id).is_dir():
            error(f"No directory found for problem {problem.id} mentioned in problems.yaml.")
            continue
        problems.append(problem)

    _problems_yaml = tuple(problems)
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


def get_request_json(r: "requests.Response") -> object:
    try:
        return r.json()
    except Exception as e:
        error(f"\nError in decoding JSON:\n{e}\n{r.text}")
    return None


def call_api_get_json(url: str) -> Any:
    r = call_api("GET", url)
    r.raise_for_status()
    return get_request_json(r)
