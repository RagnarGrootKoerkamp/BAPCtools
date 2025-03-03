import generate
import problem
from util import *

import shutil
from typing import Any


def upgrade_data(p: problem.Problem, bar: ProgressBar) -> None:
    rename = [
        ("data/invalid_inputs", "data/invalid_input"),
        ("data/invalid_answers", "data/invalid_answer"),
        ("data/invalid_outputs", "data/invalid_output"),
        ("data/valid_outputs", "data/valid_output"),
    ]
    for old_name, new_name in rename:
        old_path = p.path / old_name
        new_path = p.path / new_name
        if old_path.is_dir():
            if new_path.exists():
                bar.error(f"can't rename '{old_name}', '{new_name}' already exists", resume=True)
                continue
            bar.log(f"renaming '{old_name}' to '{new_name}'")
            old_path.rename(new_path)


def upgrade_testdata_yaml(p: problem.Problem, bar: ProgressBar) -> None:
    rename = [
        ("output_validator_flags", "output_validator_args"),
        ("inut_validator_flags", "inut_validator_args"),
    ]

    for f in (p.path / "data").rglob("testdata.yaml"):
        data = read_yaml(f)
        assert data is not None

        for old, new in rename:
            if old in data:
                if new in data:
                    bar.error(
                        f"can't change '{old}', '{new}' already exists in {f.relative_to(p.path)}",
                        resume=True,
                    )
                    continue
                data[new] = data[old]
                data.pop(old)

        write_yaml(data, f)


def upgrade_generators_yaml(p: problem.Problem, bar: ProgressBar) -> None:
    generators_yaml = p.path / "generators" / "generators.yaml"
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


def upgrade_statement(p: problem.Problem, bar: ProgressBar) -> None:
    if (p.path / "problem_statement").is_dir():
        if (p.path / "statement").exists():
            bar.error("can't rename 'problem_statement/', 'statement/' already exists", resume=True)
            return
        bar.log("renaming 'problem_statement/' to 'statement/' in generators.yaml")
        (p.path / "problem_statement").rename(p.path / "statement")

    origin = p.path / "statement"
    move = [
        ("solution*", "solution"),
        ("problem-slide*", "problem_slid"),
    ]
    for glob, dest_name in move:
        dest_path = p.path / dest_name
        if dest_path.exists() and not dest_path.is_dir():
            bar.error("'dest_name/' is not an directory", resume=True)
            continue

        for f in origin.glob(glob):
            dest = dest_path / f.relative_to(origin)
            if dest.exists():
                bar.error(
                    f"can't move '{f.relative_to(p.path)}', '{dest.relative_to(p.path)}' already exists",
                    resume=True,
                )
                continue
            bar.log(f"moving '{f.relative_to(p.path)}' to '{dest.relative_to(p.path)}'")
            dest_path.mkdir(parents=True, exist_ok=True)
            shutil.move(f, dest)


def upgrade_problem_yaml(p: problem.Problem, bar: ProgressBar) -> None:
    data = read_yaml(p.path / "problem.yaml")
    assert data is not None
    assert isinstance(data, dict)

    if "problem_format_version" not in data or data["problem_format_version"] != "2023-07-draft":
        bar.log("set 'problem_format_version' in problem.yaml")
        data["problem_format_version"] = "2023-07-draft"

    if "validation" in data:
        if "type" in data:
            bar.error(
                "can't change 'validation', 'type' already exists in problem.yaml", resume=True
            )
        else:
            bar.log("change 'validation' to 'type' in problem.yaml")
            data["type"] = ruamel.yaml.comments.CommentedSeq()
            data["type"].append("pass-fail")
            if "interactive" in data["validation"]:
                data["type"].append("interactive")
            if "multi-pass" in data["validation"]:
                data["type"].append("multi-pass")
            data.pop("validation")

    if "author" in data:
        if "credits" in data:
            bar.error(
                "can't change 'author', 'credits' already exists in problem.yaml", resume=True
            )
        else:
            bar.log("change 'author' to 'credits.authors' in problem.yaml")
            authors = data["author"].replace("and", ",").split(",")
            data["credits"] = ruamel.yaml.comments.CommentedMap()
            data["credits"]["authors"] = ruamel.yaml.comments.CommentedSeq(
                name.strip() for name in authors
            )
            data.pop("author")

    if "source_url" in data:
        if "source" not in data:
            data["source"] = ""

        bar.log("change 'source_url' to 'source.url' in problem.yaml")
        source = ruamel.yaml.comments.CommentedMap()
        source["name"] = data["source"]
        source["url"] = data["source_url"]
        data["source"] = source
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
                limits["time_multipliers"] = ruamel.yaml.comments.CommentedMap()

                if "time_multiplier" in limits:
                    limits["time_multipliers"]["ac_to_time_limit"] = limits["time_multiplier"]
                    limits.pop("time_multiplier")

                if "time_safety_margin" in limits:
                    limits["time_multipliers"]["time_limit_to_tle"] = limits["time_safety_margin"]
                    limits.pop("time_safety_margin")

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
        generators_path = p.path / "generators" / "generators.yaml"
        if generators_path.exists():
            generators_data = read_yaml(generators_path)
            assert generators_data is not None
            assert isinstance(generators_data, dict)

            if "testdata.yaml" not in generators_data:
                generators_data["testdata.yaml"] = ruamel.yaml.comments.CommentedMap()
            if add_args(generators_data["testdata.yaml"]):
                write_yaml(generators_data, generators_path)
        else:
            testdata_path = p.path / "data" / "testdata.yaml"
            testdata_data = (
                read_yaml(testdata_path)
                if testdata_path.exists()
                else ruamel.yaml.comments.CommentedMap()
            )
            assert testdata_data is not None
            assert isinstance(testdata_data, dict)

            if add_args(testdata_data):
                write_yaml(testdata_data, testdata_path)

    timelimit_path = p.path / ".timelimit"
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

    domjudge_path = p.path / "domjudge-problem.ini"
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

    write_yaml(data, p.path / "problem.yaml")


def _upgrade(p: problem.Problem, bar: ProgressBar) -> None:
    bar.start(p)

    upgrade_data(p, bar)
    upgrade_testdata_yaml(p, bar)
    upgrade_generators_yaml(p, bar)
    # upgrade_statement(p, bar) TODO: activate this when we support the new statement dirs
    # TODO: output_validators -> output_validator
    upgrade_problem_yaml(p, bar)

    bar.done()


def upgrade(problems: list[problem.Problem]) -> None:
    if not has_ryaml:
        error("upgrade needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.")
        return

    bar = ProgressBar("upgrade", items=problems)
    for p in problems:
        _upgrade(p, bar)
    bar.finalize()
