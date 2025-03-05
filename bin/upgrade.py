import config
import generate
from util import *

import shutil
from typing import Any

if has_ryaml:
    # TODO #102 The conditional import in util.py isn't picked up properly
    from ruamel.yaml.comments import CommentedMap, CommentedSeq


# This tries to preserve the correct comments.
def _filter(data: Any, remove: str) -> Any:
    assert isinstance(data, CommentedMap)

    remove_index = list(data.keys()).index(remove)
    if remove_index == 0:
        return data.pop(remove)

    curr = data
    prev_key = list(data.keys())[remove_index - 1]
    while isinstance(curr[prev_key], list | dict):
        # Try to remove the comment from the last element in the preceding list/dict
        curr = curr[prev_key]
        if isinstance(curr, list):
            prev_key = len(curr) - 1
        else:
            prev_key = list(curr.keys())[-1]

    if remove in data.ca.items:
        # Move the comment that belongs to the removed key (which comes _after_ the removed key)
        # to the preceding key
        curr.ca.items[prev_key] = data.ca.items.pop(remove)
    elif prev_key in data.ca.items:
        # If the removed key does not have a comment,
        # the comment after the previous key should be removed
        curr.ca.items.pop(prev_key)

    return data.pop(remove)


# Insert a new key before an old key, then remove the old key.
# If new_value is not given, the default is to simply rename the old key to the new key.
def _replace(data: Any, old_key: str, new_key: str, new_value: Any = None) -> None:
    if new_value is None:
        new_value = data[old_key]
    data.insert(list(data.keys()).index(old_key), new_key, new_value)
    _filter(data, old_key)


def upgrade_data(problem_path: Path, bar: ProgressBar) -> None:
    rename = [
        ("data/invalid_inputs", "data/invalid_input"),
        ("data/invalid_answers", "data/invalid_answer"),
        ("data/invalid_outputs", "data/invalid_output"),
        ("data/valid_outputs", "data/valid_output"),
    ]
    for old_name, new_name in rename:
        old_path = problem_path / old_name
        new_path = problem_path / new_name
        if old_path.is_dir():
            if new_path.exists():
                bar.error(f"can't rename '{old_name}', '{new_name}' already exists", resume=True)
                continue
            bar.log(f"renaming '{old_name}' to '{new_name}'")
            old_path.rename(new_path)


def upgrade_testdata_yaml(problem_path: Path, bar: ProgressBar) -> None:
    rename = [
        ("output_validator_flags", "output_validator_args"),
        ("input_validator_flags", "input_validator_args"),
    ]

    for f in (problem_path / "data").rglob("testdata.yaml"):
        data = read_yaml(f)
        assert data is not None

        for old, new in rename:
            if old in data:
                if new in data:
                    bar.error(
                        f"can't change '{old}', '{new}' already exists in {f.relative_to(problem_path)}",
                        resume=True,
                    )
                    continue
                _replace(data, old, new)

        write_yaml(data, f)


def upgrade_generators_yaml(problem_path: Path, bar: ProgressBar) -> None:
    generators_yaml = problem_path / "generators" / "generators.yaml"
    if not generators_yaml.is_file():
        return
    data = read_yaml(generators_yaml)
    if data is None or not isinstance(data, dict):
        return

    changed = False

    rename = [
        ("invalid_inputs", "invalid_input"),
        ("invalid_answers", "invalid_answer"),
        ("invalid_outputs", "invalid_output"),
        ("valid_outputs", "valid_output"),
    ]
    for old_name, new_name in rename:
        if old_name in data:
            if new_name in data:
                bar.error(
                    f"can't rename 'data.{old_name}', 'data.{new_name}' already exists in generators.yaml",
                    resume=True,
                )
                continue
            bar.log(f"renaming 'data.{old_name}' to 'data.{new_name}' in generators.yaml")
            _replace(data, old_name, new_name)
            changed = True

    def upgrade_generated_testdata_yaml(data: dict[str, Any], path: str) -> bool:
        changed = False
        if "testdata.yaml" in data:
            testdata = data["testdata.yaml"]
            assert isinstance(testdata, dict)
            print_path = f" ({path[1:]})" if len(path) > 1 else ""

            rename = [
                ("output_validator_flags", "output_validator_args"),
                ("input_validator_flags", "input_validator_args"),
            ]
            for old, new in rename:
                if old in testdata:
                    if new in testdata:
                        bar.error(
                            f"can't change '{old}', '{new}' already exists in generators.yaml{print_path}",
                            resume=True,
                        )
                        continue
                    bar.log(f"change '{old}' to '{new}' in generators.yaml{print_path}")
                    _replace(testdata, old, new)
                    changed = True
        if "data" in data and data["data"]:
            children = data["data"] if isinstance(data["data"], list) else [data["data"]]
            for dictionary in children:
                for child_name, child_data in sorted(dictionary.items()):
                    if generate.is_directory(child_data):
                        changed |= upgrade_generated_testdata_yaml(
                            child_data, path + "." + child_name
                        )
        return changed

    changed |= upgrade_generated_testdata_yaml(data, "")

    if changed:
        write_yaml(data, generators_yaml)


def upgrade_statement(problem_path: Path, bar: ProgressBar) -> None:
    if (problem_path / "problem_statement").is_dir():
        if (problem_path / "statement").exists():
            bar.error("can't rename 'problem_statement/', 'statement/' already exists", resume=True)
        else:
            bar.log("renaming 'problem_statement/' to 'statement/'")
            (problem_path / "problem_statement").rename(problem_path / "statement")

    origin = problem_path / "statement"
    move = [
        ("solution*", "solution"),
        ("problem-slide*", "problem_slide"),
    ]
    for glob, dest_name in move:
        dest_path = problem_path / dest_name
        if dest_path.exists() and not dest_path.is_dir():
            bar.error(f"'{dest_name}' is not a directory", resume=True)
            continue

        for f in origin.glob(glob):
            dest = dest_path / f.relative_to(origin)
            if dest.exists():
                bar.error(
                    f"can't move '{f.relative_to(problem_path)}', '{dest.relative_to(problem_path)}' already exists",
                    resume=True,
                )
                continue
            bar.log(f"moving '{f.relative_to(problem_path)}' to '{dest.relative_to(problem_path)}'")
            dest_path.mkdir(parents=True, exist_ok=True)
            shutil.move(f, dest)


def upgrade_problem_yaml(problem_path: Path, bar: ProgressBar) -> None:
    assert (problem_path / "problem.yaml").exists()
    data = cast(CommentedMap, read_yaml(problem_path / "problem.yaml"))
    assert data is not None
    assert isinstance(data, dict)

    if (
        "problem_format_version" not in data
        or data["problem_format_version"] != config.SPEC_VERSION
    ):
        bar.log("set 'problem_format_version' in problem.yaml")
        data.insert(0, "problem_format_version", config.SPEC_VERSION)

    if "validation" in data:
        if "type" in data:
            bar.error(
                "can't change 'validation', 'type' already exists in problem.yaml", resume=True
            )
        else:
            bar.log("change 'validation' to 'type' in problem.yaml")
            type = CommentedSeq()
            if "interactive" in data["validation"]:
                type.append("interactive")
            if "multi-pass" in data["validation"]:
                type.append("multi-pass")
            if not type:
                type.append("pass-fail")
            # "type" comes before "name" in the spec
            pos = list(data.keys()).index("name") if "name" in data else 0
            data.insert(pos, "type", type if len(type) > 1 else type[0])
            _filter(data, "validation")

    if "author" in data:
        if "credits" in data:
            bar.error(
                "can't change 'author', 'credits' already exists in problem.yaml", resume=True
            )
        else:
            bar.log("change 'author' to 'credits.authors' in problem.yaml")
            authors = CommentedSeq(
                name.strip() for name in data["author"].replace("and", ",").split(",")
            )
            credits = CommentedMap({"authors": authors if len(authors) > 1 else authors[0]})
            _replace(data, "author", "credits", credits)

    if "source_url" in data:
        if "source" not in data:
            _replace(data, "source_url", "source")
        elif data["source"]:
            bar.log("change 'source_url' to 'source.url' in problem.yaml")
            old_pos = list(data.keys()).index("source")
            old_source = _filter(data, "source")
            old_source_url = _filter(data, "source_url")
            data.insert(
                old_pos, "source", CommentedMap({"name": old_source, "url": old_source_url})
            )
        else:
            bar.log("remove empty 'source(_url)' in problem.yaml")
            _filter(data, "source")
            _filter(data, "source_url")

    if "limits" in data:
        limits = data["limits"]
        if "time_multiplier" in limits or "time_safety_margin" in limits:
            if "time_multipliers" in limits:
                bar.error(
                    "can't change 'limits.time_multiplier/limits.time_safety_margin', 'limits.time_multipliers' already exists in problem.yaml",
                    resume=True,
                )
            else:
                bar.log(
                    "change 'limits.time_multiplier/limits.time_safety_margin' to 'limits.time_multipliers'"
                )
                time_multipliers = CommentedMap()

                if "time_multiplier" in limits:
                    if limits["time_multiplier"] != 2:  # Skip if it's equal to the new default
                        time_multipliers["ac_to_time_limit"] = limits["time_multiplier"]
                    _filter(limits, "time_multiplier")

                if "time_safety_margin" in limits:
                    if limits["time_safety_margin"] != 1.5:  # Skip if it's equal to the new default
                        time_multipliers["time_limit_to_tle"] = limits["time_safety_margin"]
                    _filter(limits, "time_safety_margin")

                if time_multipliers:
                    limits["time_multipliers"] = time_multipliers
                # If both time multipliers are default, remove the comments (this only works if
                # there are no other limits configured, but that's the most common case anyway)
                if not limits:
                    _filter(data, "limits")

    def add_args(new_data: dict[str, Any]) -> bool:
        if "output_validator_args" in new_data:
            bar.error(
                "can't change 'validator_flags', 'output_validator_args' already exists in testdata.yaml",
                resume=True,
            )
            return False
        bar.log("change 'validator_flags' to 'output_validator_args' in testdata.yaml")
        new_data["output_validator_args"] = data["validator_flags"]
        _filter(data, "validator_flags")
        return True

    if "validator_flags" in data:
        generators_path = problem_path / "generators" / "generators.yaml"
        if generators_path.exists():
            generators_data = read_yaml(generators_path)
            assert generators_data is not None
            assert isinstance(generators_data, CommentedMap)

            if "testdata.yaml" not in generators_data:
                if "data" in generators_data:
                    # insert before data
                    pos = list(generators_data.keys()).index("data")
                    generators_data.insert(pos, "testdata.yaml", CommentedMap())
                else:
                    # insert at end
                    generators_data["testdata.yaml"] = CommentedMap()
            if add_args(generators_data["testdata.yaml"]):
                write_yaml(generators_data, generators_path)
        else:
            testdata_path = problem_path / "data" / "testdata.yaml"
            testdata_data = read_yaml(testdata_path) if testdata_path.exists() else CommentedMap()
            assert testdata_data is not None
            assert isinstance(testdata_data, dict)

            if add_args(testdata_data):
                write_yaml(testdata_data, testdata_path)

    timelimit_path = problem_path / ".timelimit"
    if timelimit_path.is_file():
        if "limits" not in data:
            data["limits"] = CommentedMap()
        if "time_limit" in data["limits"]:
            bar.error(
                "can't change '.timelimit' file, 'limits.time_limit' already exists in problem.yaml",
                resume=True,
            )
        else:
            bar.log("change '.timelimit' file to 'limits.time_limit' in problem.yaml")
            data["limits"]["time_limit"] = float(timelimit_path.read_text())
            timelimit_path.unlink()

    domjudge_path = problem_path / "domjudge-problem.ini"
    if domjudge_path.is_file():
        time_limit = None
        for line in domjudge_path.read_text().splitlines():
            key, var = map(str.strip, line.strip().split("="))
            if (var[0] == '"' or var[0] == "'") and (var[-1] == '"' or var[-1] == "'"):
                var = var[1:-1]
            if key == "timelimit":
                time_limit = float(var)
        if time_limit is not None:
            if "limits" not in data:
                data["limits"] = CommentedMap()
            if "time_limit" in data["limits"]:
                bar.error(
                    "can't change '.timelimit' file, 'limits.time_limit' already exists in problem.yaml",
                    resume=True,
                )
            else:
                bar.log("change 'domjudge-problem.ini' file to 'limits.time_limit' in problem.yaml")
                data["limits"]["time_limit"] = time_limit
                domjudge_path.unlink()

    write_yaml(data, problem_path / "problem.yaml")


def _upgrade(problem_path: Path, bar: ProgressBar) -> None:
    bar.start(problem_path)

    upgrade_data(problem_path, bar)
    upgrade_testdata_yaml(problem_path, bar)
    upgrade_generators_yaml(problem_path, bar)
    upgrade_statement(problem_path, bar)
    # TODO: output_validators -> output_validator
    upgrade_problem_yaml(problem_path, bar)

    bar.done()


def upgrade() -> None:
    if not has_ryaml:
        error("upgrade needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.")
        return
    cwd = Path().cwd()

    def is_problem_directory(path):
        return (path / "problem.yaml").is_file()

    if is_problem_directory(cwd):
        paths = [cwd]
    else:
        paths = [p for p in cwd.iterdir() if is_problem_directory(p)]

    bar = ProgressBar("upgrade", items=paths)
    for path in paths:
        _upgrade(path, bar)
    bar.finalize()
