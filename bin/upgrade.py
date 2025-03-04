import config
import generate
from util import *

import shutil
from typing import Any


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
        ("inut_validator_flags", "inut_validator_args"),
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
                data[new] = data[old]
                data.pop(old)

        write_yaml(data, f)


def upgrade_generators_yaml(problem_path: Path, bar: ProgressBar) -> None:
    generators_yaml = problem_path / "generators" / "generators.yaml"
    if not generators_yaml.is_file():
        return
    data = read_yaml(generators_yaml)
    if data is None or not isinstance(data, dict):
        return

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
            data[new_name] = data[old_name]
            data.pop(old_name)

    def upgrade_generated_testdata_yaml(data: dict[str, Any], path: str) -> None:
        if "testdata.yaml" in data:
            testdata = data["testdata.yaml"]
            assert isinstance(testdata, dict)
            print_path = f" ({path[1:]})" if len(path) > 1 else ""

            rename = [
                ("output_validator_flags", "output_validator_args"),
                ("inut_validator_flags", "inut_validator_args"),
            ]
            for old, new in rename:
                if old in testdata:
                    if new in testdata:
                        bar.error(
                            f"can't change '{old}', '{new}' already exists in generators.yaml{print_path}",
                            resume=True,
                        )
                        continue
                    bar.log(
                        f"change '{old}' to '{new}' in generators.yaml{print_path}",
                        resume=True,
                    )
                    testdata[new] = testdata[old]
                    testdata.pop(old)
        if "data" in data and data["data"]:
            children = data["data"] if isinstance(data["data"], list) else [data["data"]]
            for dictionary in children:
                for child_name, child_data in sorted(dictionary.items()):
                    if generate.is_directory(child_data):
                        upgrade_generated_testdata_yaml(child_data, path + "." + child_name)

    upgrade_generated_testdata_yaml(data, "")

    write_yaml(data, generators_yaml)


def upgrade_statement(problem_path: Path, bar: ProgressBar) -> None:
    if (problem_path / "problem_statement").is_dir():
        if (problem_path / "statement").exists():
            bar.error("can't rename 'problem_statement/', 'statement/' already exists", resume=True)
            return
        bar.log("renaming 'problem_statement/' to 'statement/' in generators.yaml")
        (problem_path / "problem_statement").rename(problem_path / "statement")

    origin = problem_path / "statement"
    move = [
        ("solution*", "solution"),
        ("problem-slide*", "problem_slid"),
    ]
    for glob, dest_name in move:
        dest_path = problem_path / dest_name
        if dest_path.exists() and not dest_path.is_dir():
            bar.error("'dest_name/' is not an directory", resume=True)
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
    data = cast(ruamel.yaml.comment.CommentedMap, read_yaml(problem_path / "problem.yaml"))
    assert data is not None
    assert isinstance(data, dict)

    if (
        "problem_format_version" not in data
        or data["problem_format_version"] != config.SPEC_VERSION
    ):
        bar.log("set 'problem_format_version' in problem.yaml")
        data["problem_format_version"] = config.SPEC_VERSION

    if "validation" in data:
        if "type" in data:
            bar.error(
                "can't change 'validation', 'type' already exists in problem.yaml", resume=True
            )
        else:
            bar.log("change 'validation' to 'type' in problem.yaml")
            type = ruamel.yaml.comments.CommentedSeq()
            if "interactive" in data["validation"]:
                type.append("interactive")
            if "multi-pass" in data["validation"]:
                type.append("multi-pass")
            if not type:
                type.append("pass-fail")
            data["type"] = type if len(type) > 1 else type[0]
            data.pop("validation")

    if "author" in data:
        if "credits" in data:
            bar.error(
                "can't change 'author', 'credits' already exists in problem.yaml", resume=True
            )
        else:
            bar.log("change 'author' to 'credits.authors' in problem.yaml")
            authors = ruamel.yaml.comments.CommentedSeq(
                name.strip() for name in data["author"].replace("and", ",").split(",")
            )
            data["credits"] = ruamel.yaml.comments.CommentedMap()
            data["credits"]["authors"] = authors if len(authors) > 1 else authors[0]
            data.pop("author")

    if "source_url" in data:
        if "source" not in data:
            data["source"] = data["source_url"]
        if data["source"]:
            bar.log("change 'source_url' to 'source.url' in problem.yaml")
            source = ruamel.yaml.comments.CommentedMap()
            source["name"] = data["source"]
            source["url"] = data["source_url"]
            data["source"] = source
        else:
            bar.log("remove empty 'source(_url)' in problem.yaml")
            data.pop("source")
        data.pop("source_url")

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
                time_multipliers = ruamel.yaml.comments.CommentedMap()

                if "time_multiplier" in limits:
                    if limits["time_multiplier"] != 2:  # Skip if it's equal to the new default
                        time_multipliers["ac_to_time_limit"] = limits["time_multiplier"]
                    limits.pop("time_multiplier")

                if "time_safety_margin" in limits:
                    if limits["time_safety_margin"] != 1.5:  # Skip if it's equal to the new default
                        time_multipliers["time_limit_to_tle"] = limits["time_safety_margin"]
                    limits.pop("time_safety_margin")

                if time_multipliers:
                    limits["time_multipliers"] = time_multipliers
                # If both time multipliers are default, remove the comments (this only works if
                # there are no other limits configured, but that's the most common case anyway)
                if not limits:
                    if "limits" in data.ca.items:
                        data.ca.items.pop("limits")
                    data.pop("limits")

    def add_args(new_data: dict[str, Any]) -> bool:
        if "output_validator_args" in new_data:
            bar.error(
                "can't change 'validator_flags', 'output_validator_args' already exists in testdata.yaml",
                resume=True,
            )
            return False
        bar.log("change 'validator_flags' to 'output_validator_args' in testdata.yaml")
        new_data["output_validator_args"] = data["validator_flags"]
        data.pop("validator_flags")
        return True

    if "validator_flags" in data:
        generators_path = problem_path / "generators" / "generators.yaml"
        if generators_path.exists():
            generators_data = read_yaml(generators_path)
            assert generators_data is not None
            assert isinstance(generators_data, dict)

            if "testdata.yaml" not in generators_data:
                generators_data["testdata.yaml"] = ruamel.yaml.comments.CommentedMap()
            if add_args(generators_data["testdata.yaml"]):
                write_yaml(generators_data, generators_path)
        else:
            testdata_path = problem_path / "data" / "testdata.yaml"
            testdata_data = (
                read_yaml(testdata_path)
                if testdata_path.exists()
                else ruamel.yaml.comments.CommentedMap()
            )
            assert testdata_data is not None
            assert isinstance(testdata_data, dict)

            if add_args(testdata_data):
                write_yaml(testdata_data, testdata_path)

    timelimit_path = problem_path / ".timelimit"
    if timelimit_path.is_file():
        if "limits" not in data:
            data["limits"] = ruamel.yaml.comments.CommentedMap()
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
                data["limits"] = ruamel.yaml.comments.CommentedMap()
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
    # upgrade_statement(problem_path, bar) TODO: activate this when we support the new statement dirs
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
