import config
import generate
from util import *
from validate import InputValidator, AnswerValidator, OutputValidator

import secrets
import shutil
from pathlib import Path
from typing import Any, cast

if has_ryaml:
    # TODO #102 The conditional import in util.py isn't picked up properly
    from ruamel.yaml.comments import CommentedMap, CommentedSeq


# src_base must be a dir (or symlink to dir)
# dst_base must not exists
# the parents of dst_base must exist
def _move_dir(src_base: Path, dst_base: Path) -> None:
    assert src_base.is_dir()
    assert not dst_base.exists()

    src_base = src_base.absolute()
    dst_base = dst_base.absolute()
    base = [a for a, b in zip(reversed(src_base.parents), reversed(dst_base.parents)) if a == b][-1]

    def resolve_up(parts: tuple[str, ...]) -> Path:
        resolved: list[str] = []
        for part in parts:
            if part == ".":
                continue
            if part == ".." and len(resolved) and resolved[-1] != "..":
                resolved.pop()
            else:
                resolved.append(part)
        return Path(*resolved)

    def movetree(src: Path, dst: Path) -> None:
        if src.is_symlink():
            # create a new symlink and make sure that the destination is handled properly
            destination = src.readlink()
            if destination.is_absolute():
                # absolute links should stay absolute
                # if their destination is inside the dir we move we have to change it
                if destination.is_relative_to(src_base):
                    destination = dst_base / destination.relative_to(src_base)
                dst.symlink_to(destination)
                src.unlink()
            else:
                if resolve_up(src.parent.parts + destination.parts).is_relative_to(src_base):
                    # the link is relative and points to another file we move
                    src.rename(dst)
                else:
                    # the link is relative but points to a fixed place
                    src_rel = src.parent.relative_to(base)
                    dst_rel = dst.parent.relative_to(base)
                    parts = (("..",) * len(dst_rel.parts)) + src_rel.parts + destination.parts
                    dst.symlink_to(resolve_up(parts))
                    src.unlink()
        elif src.is_dir():
            # recursively move stuff inside dirs
            dst.mkdir()
            for file in [*src.iterdir()]:
                movetree(file, dst / file.name)
            # delete now empty dir
            src.rmdir()
        else:
            # move file
            src.rename(dst)

    movetree(src_base, dst_base)


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

    def rename_testcase(old_base: Path, new_dir: Path) -> None:
        new_dir.mkdir(parents=True, exist_ok=True)
        new_base = new_dir / old_base.name
        for ext in config.KNOWN_TEXT_DATA_EXTENSIONS:
            old_path = old_base.with_suffix(ext)
            new_path = new_base.with_suffix(ext)
            if old_path.is_file():
                old_rel_path, new_rel_path = [
                    p.relative_to(problem_path) for p in (old_path, new_path)
                ]
                if new_path.exists():
                    bar.error(
                        f"can't rename '{old_rel_path}', '{new_rel_path}' already exists",
                        resume=True,
                    )
                    continue
                bar.log(f"renaming '{old_rel_path}' to '{new_rel_path}'")
                old_path.rename(new_path)

    bad_dir = problem_path / "data" / "bad"
    for file in bad_dir.glob("*.in"):
        if file.with_suffix(".ans").is_file():
            rename_testcase(file, problem_path / "data" / "invalid_answer")
        else:
            rename_testcase(file, problem_path / "data" / "invalid_input")
    if bad_dir.is_dir() and not any(bad_dir.iterdir()):
        bad_dir.rmdir()


def upgrade_testdata_yaml(problem_path: Path, bar: ProgressBar) -> None:
    rename = [
        ("output_validator_flags", OutputValidator.args_key),
        ("input_validator_flags", InputValidator.args_key),
    ]

    for f in (problem_path / "data").rglob("testdata.yaml"):
        data = cast(CommentedMap, read_yaml(f))

        for old, new in rename:
            if old in data:
                if new in data:
                    bar.error(
                        f"can't change '{old}', '{new}' already exists in {f.relative_to(problem_path)}",
                        resume=True,
                    )
                    continue
                ryaml_replace(data, old, new)

        write_yaml(data, f)


def upgrade_generators_yaml(problem_path: Path, bar: ProgressBar) -> None:
    generators_yaml = problem_path / "generators" / "generators.yaml"
    if not generators_yaml.is_file():
        return
    yaml_data = read_yaml(generators_yaml)
    if yaml_data is None or not isinstance(yaml_data, dict):
        return

    changed = False

    if "visualizer" in yaml_data:
        warn(
            "Cannot automatically upgrade 'visualizer'.\n - move visualizer to 'input_visualizer/'\n - first argument is the in_file\n - second argument is the ans_file"
        )

    if "data" in yaml_data and isinstance(yaml_data["data"], dict):
        data = cast(CommentedMap, yaml_data["data"])

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
                ryaml_replace(data, old_name, new_name)
                changed = True

        # this breaks comments... but that is fine
        if "bad" in data:

            def move_testcase(name: str, value: Any, new_parent: str) -> None:
                parent = ryaml_get_or_add(data, new_parent)
                if "data" not in parent:
                    parent[data] = CommentedSeq
                parent = parent["data"]
                new_name = name
                if isinstance(parent, list):
                    parent.append(CommentedMap())
                    parent[-1][new_name] = value
                else:
                    if new_name in parent:
                        new_name = f"bad_{new_name}"
                    if new_name in parent:
                        new_name = f"{new_name}_{secrets.token_hex(6)}"
                    assert new_name not in parent
                    parent[new_name] = value
                bar.log(f"renaming 'bad.{name}' to '{new_parent}.{new_name}' in generators.yaml")

            bad = data["bad"]
            if "data" in bad and bad["data"]:
                children = bad["data"] if isinstance(bad["data"], list) else [bad["data"]]
                for dictionary in children:
                    for child_name, child_data in sorted(dictionary.items()):
                        if "ans" in child_data:
                            move_testcase(child_name, child_data, "invalid_answer")
                        else:
                            move_testcase(child_name, child_data, "invalid_input")

            ryaml_filter(data, "bad")
            changed = True

    def upgrade_generated_testdata_yaml(data: dict[str, Any], path: str) -> bool:
        changed = False
        if "testdata.yaml" in data:
            testdata = cast(CommentedMap, data["testdata.yaml"])
            print_path = f" ({path[1:]})" if len(path) > 1 else ""

            rename = [
                ("output_validator_flags", OutputValidator.args_key),
                ("input_validator_flags", InputValidator.args_key),
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
                    ryaml_replace(testdata, old, new)
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

    changed |= upgrade_generated_testdata_yaml(yaml_data, "")

    if changed:
        write_yaml(yaml_data, generators_yaml)


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


def upgrade_format_validators(problem_path: Path, bar: ProgressBar) -> None:
    rename = [
        ("input_format_validators", InputValidator.source_dir),
        ("answer_format_validators", AnswerValidator.source_dir),
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


def upgrade_output_validators(problem_path: Path, bar: ProgressBar) -> None:
    if (problem_path / "output_validators").is_dir():
        if (problem_path / OutputValidator.source_dir).exists():
            bar.error(
                f"can't rename 'output_validators/', '{OutputValidator.source_dir}/' already exists",
                resume=True,
            )
            return
        content = [*(problem_path / "output_validators").iterdir()]
        if len(content) == 1 and content[0].is_dir():
            bar.log(
                f"renaming 'output_validators/{content[0].name}' to '{OutputValidator.source_dir}/'"
            )
            _move_dir(content[0], problem_path / OutputValidator.source_dir)
        else:
            bar.log(f"renaming 'output_validators/' to '{OutputValidator.source_dir}/'")
            (problem_path / "output_validators").rename(problem_path / OutputValidator.source_dir)


def upgrade_problem_yaml(problem_path: Path, bar: ProgressBar) -> None:
    assert (problem_path / "problem.yaml").exists()
    data = cast(CommentedMap, read_yaml(problem_path / "problem.yaml"))

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
            ryaml_filter(data, "validation")

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
            ryaml_replace(data, "author", "credits", credits)

    if "source_url" in data:
        if "source" not in data:
            ryaml_replace(data, "source_url", "source")
        elif data["source"]:
            bar.log("change 'source_url' to 'source.url' in problem.yaml")
            old_pos = list(data.keys()).index("source")
            old_source = ryaml_filter(data, "source")
            old_source_url = ryaml_filter(data, "source_url")
            data.insert(
                old_pos, "source", CommentedMap({"name": old_source, "url": old_source_url})
            )
        else:
            bar.log("remove empty 'source(_url)' in problem.yaml")
            ryaml_filter(data, "source")
            ryaml_filter(data, "source_url")

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
                    ryaml_filter(limits, "time_multiplier")

                if "time_safety_margin" in limits:
                    if limits["time_safety_margin"] != 1.5:  # Skip if it's equal to the new default
                        time_multipliers["time_limit_to_tle"] = limits["time_safety_margin"]
                    ryaml_filter(limits, "time_safety_margin")

                if time_multipliers:
                    limits["time_multipliers"] = time_multipliers
                # If both time multipliers are default, remove the comments (this only works if
                # there are no other limits configured, but that's the most common case anyway)
                if not limits:
                    ryaml_filter(data, "limits")

    def add_args(new_data: dict[str, Any]) -> bool:
        if OutputValidator.args_key in new_data:
            bar.error(
                f"can't change 'validator_flags', '{OutputValidator.args_key}' already exists in testdata.yaml",
                resume=True,
            )
            return False
        bar.log(f"change 'validator_flags' to '{OutputValidator.args_key}' in testdata.yaml")
        validator_flags = data["validator_flags"]
        new_data[OutputValidator.args_key] = (
            validator_flags.split() if isinstance(validator_flags, str) else validator_flags
        )
        ryaml_filter(data, "validator_flags")
        return True

    if "validator_flags" in data:
        if data["validator_flags"]:
            generators_path = problem_path / "generators" / "generators.yaml"
            if generators_path.exists():
                generators_data = cast(CommentedMap, read_yaml(generators_path))

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
                testdata_data = (
                    cast(CommentedMap, read_yaml(testdata_path))
                    if testdata_path.exists()
                    else CommentedMap()
                )

                if add_args(testdata_data):
                    write_yaml(testdata_data, testdata_path)
        else:
            ryaml_filter(data, "validator_flags")

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
                    "can't change 'domjudge-problem.ini' file, 'limits.time_limit' already exists in problem.yaml",
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
    upgrade_format_validators(problem_path, bar)
    upgrade_output_validators(problem_path, bar)
    upgrade_problem_yaml(problem_path, bar)

    bar.done()


def upgrade() -> None:
    if not has_ryaml:
        error("upgrade needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.")
        return
    cwd = Path().cwd()

    def is_problem_directory(path: Path) -> bool:
        return (path / "problem.yaml").is_file()

    if is_problem_directory(cwd):
        paths = [cwd]
    else:
        paths = [p for p in cwd.iterdir() if is_problem_directory(p)]

    bar = ProgressBar("upgrade", items=paths)
    for path in paths:
        _upgrade(path, bar)
    bar.finalize()
