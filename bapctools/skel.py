import datetime
import os
import re
import shutil
from pathlib import Path

# Local imports
from bapctools import config, contest, latex
from bapctools.problem import Problem
from bapctools.util import (
    ask_variable_bool,
    ask_variable_choice,
    ask_variable_string,
    copytree_and_substitute,
    error,
    fatal,
    generate_problem_uuid,
    inc_label,
    log,
    read_yaml,
    ShellCommand,
    substitute,
    warn,
    write_yaml,
)
from bapctools.validate import OutputValidator


# Returns the alphanumeric version of a string:
# This reduces it to a string that follows the regex:
# [a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]
def _alpha_num(string: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_.-]", "", string.lower().replace(" ", "").replace("-", ""))
    while len(s) and s[0] in "_.-":
        s = s[1:]
    while len(s) and s[-1] in "_.-":
        s = s[:-1]
    return s


def new_contest() -> None:
    if config.args.contest:
        fatal("--contest does not work for new_contest.")
    if config.args.problem:
        fatal("--problem does not work for new_contest.")

    # Ask for all required infos.
    title = ask_variable_string("name", config.args.contestname)
    subtitle = ask_variable_string("subtitle", "", True).replace("_", "-")
    dirname = ask_variable_string("dirname", _alpha_num(title))
    author = ask_variable_string("author", f"The {title} Jury").replace("_", "-")
    test_session = ask_variable_bool("test session", False)
    year = ask_variable_string("year", str(datetime.datetime.now().year))
    source_url = ask_variable_string("source url", "", True)
    license = ask_variable_choice("license", config.KNOWN_LICENSES)
    rights_owner = ask_variable_string(
        "rights owner (if left empty, defaults to problem author)", "", allow_empty=True
    )
    rights_owner = f"rights_owner: {rights_owner}\n" if rights_owner else ""
    title = title.replace("_", "-")

    skeldir = config.RESOURCES_ROOT / "skel/contest"
    log(f"Copying {skeldir} to {dirname}.")
    copytree_and_substitute(
        skeldir, Path(dirname), locals(), exist_ok=False, preserve_symlinks=False
    )


def get_skel_dir(target_dir: Path) -> tuple[Path, bool]:
    skeldir = config.RESOURCES_ROOT / "skel/problem"
    preserve_symlinks = False
    if (target_dir / "skel/problem").is_dir():
        skeldir = target_dir / "skel/problem"
        preserve_symlinks = True
    if (target_dir / "../skel/problem").is_dir():
        skeldir = target_dir / "../skel/problem"
        preserve_symlinks = True
    if config.args.skel:
        skeldir = Path(config.args.skel)
        preserve_symlinks = True
    return (skeldir, preserve_symlinks)


def new_problem() -> None:
    target_dir = Path(".")
    if config.args.contest:
        os.chdir(Path(config.args.contest))
    if config.args.problem:
        fatal("--problem does not work for new_problem.")

    statement_languages = config.args.lang if config.args.lang else ["en"]
    main_language = "en" if "en" in statement_languages else statement_languages[0]

    problemname = {
        lang: (
            config.args.problemname
            if config.args.problemname
            else ask_variable_string(f"problem name ({lang})")
        )
        for lang in statement_languages
    }
    dirname = (
        _alpha_num(config.args.problemname)
        if config.args.problemname
        else ask_variable_string("dirname", _alpha_num(problemname[main_language]))
    )
    author = config.args.author if config.args.author else ask_variable_string("author")

    output_validator_args = f"#{OutputValidator.args_key}:"
    custom_output = False
    if config.args.type:
        problem_type = config.args.type
    else:
        problem_type = ask_variable_choice(
            "type",
            ["pass-fail", "float", "custom", "interactive", "multi-pass", "interactive multi-pass"],
        )
    # The validation type `float` is not official, it only helps setting the `output_validator_args`.
    if problem_type == "float":
        problem_type = "pass-fail"
        output_validator_args = f'{OutputValidator.args_key}: [float_tolerance, "1e-6"]'
        log("Using default float tolerance of 1e-6")
    # Since version 2025-09 of the spec, the `custom` validation type is no longer explicit.
    # The mere existence of the output_validator(s)/ folder signals non-default output validation.
    if problem_type == "custom":
        custom_output = True
        problem_type = "pass-fail"
    if "interactive" in problem_type or "multi-pass" in problem_type:
        custom_output = True

    # Convert settings from the contest-level yaml file to strings so they can be used to substitute.
    contest_data = {k: str(v) for k, v in contest.contest_yaml().dict().items()}
    variables = {
        **contest_data,
        "problemname": "\n".join(f"  {lang}: {name}" for lang, name in problemname.items()),
        "dirname": dirname,
        "author": author,
        "type": problem_type,
        OutputValidator.args_key: output_validator_args,
        "test_group_yaml_comment": "#" if output_validator_args[0] == "#" else "",
    }

    source_name = ask_variable_string(
        "source", variables.get("source", variables.get("name", "")), True
    )
    if source_name:
        source_url = ask_variable_string("source url", variables.get("source_url", ""), True)
        variables["source"] = (
            f"source:\n  name: {source_name}\n{f'  url: {source_url}' if source_url else '  #url:'}\n"
        )
    else:
        variables["source"] = ""

    variables["license"] = ask_variable_choice(
        "license", config.KNOWN_LICENSES, variables.get("license", None)
    )
    variables["rights_owner"] = ask_variable_string(
        f"rights owner{'' if variables.get('rights_owner', '') else ' (if left empty, defaults to problem author)'}",
        variables.get("rights_owner", ""),
        allow_empty=True,
    )
    variables["rights_owner"] = (
        f"rights_owner: {variables['rights_owner']}\n" if variables["rights_owner"] else ""
    )
    variables["uuid"] = generate_problem_uuid()

    # Copy tree from the skel directory, next to the contest, if it is found.
    skeldir, preserve_symlinks = get_skel_dir(target_dir)
    log(f"Copying {skeldir} to {target_dir / dirname}.")

    if config.SPEC_VERSION not in (skeldir / "problem.yaml").read_text():
        fatal(
            f"new_problem only supports `skel` directories where `problem.yaml` has `version: {config.SPEC_VERSION}`."
        )

    problems_yaml = target_dir / "problems.yaml"

    if problems_yaml.is_file():
        data = read_yaml(problems_yaml) or []
        assert isinstance(data, list)
        prev_label = data[-1]["label"] if data else None
        next_label = (
            ("X" if contest.contest_yaml().test_session else "A")
            if prev_label is None
            else inc_label(prev_label)
        )
        # Name and time limits are overridden by problem.yaml, but still required.
        data.append(
            {
                "id": dirname,
                "label": next_label,
                "name": problemname,
                "rgb": "#000000",
                "time_limit": 1.0,
            }
        )
        write_yaml(data, problems_yaml)

    skip = []
    if not custom_output:
        skip.append(skeldir / OutputValidator.source_dir)

    copytree_and_substitute(
        skeldir,
        target_dir / dirname,
        variables,
        exist_ok=True,
        preserve_symlinks=preserve_symlinks,
        skip=skip,
    )

    # Warn about missing problem statement skeletons for non-en languages
    for lang in statement_languages:
        statement_path = target_dir / dirname / latex.PdfType.PROBLEM.path(lang)
        if not statement_path.is_file():
            warn(
                f"No skeleton for {statement_path.name} found. Create it manually or update skel/problem."
            )


def rename_problem(problem: Problem) -> None:
    newname = {
        lang: (
            config.args.problemname
            if config.args.problemname
            else ask_variable_string(f"New problem name ({lang})", problem.settings.name[lang])
        )
        for lang in problem.statement_languages
    }
    dirname = (
        _alpha_num(config.args.problemname)
        if config.args.problemname
        else ask_variable_string("dirname", _alpha_num(newname[problem.statement_languages[0]]))
    )

    shutil.move(problem.name, dirname)

    problem_yaml = Path(dirname) / "problem.yaml"
    data = read_yaml(problem_yaml)
    if not isinstance(data, dict):
        error("could not parse problem.yaml.")
        return
    data["name"] = newname
    write_yaml(data, problem_yaml)

    problems_yaml = Path("problems.yaml")
    if problems_yaml.is_file():
        data = read_yaml(problems_yaml) or []
        if not isinstance(data, list) or not all(isinstance(p, dict) for p in data):
            error("could not parse problems.yaml. Must be a list of problems.")
        else:
            prob = next((p for p in data if p["id"] == problem.name), None)
            if prob is not None:
                prob["id"] = dirname
                prob["name"] = newname
                write_yaml(data, problems_yaml)


def copy_skel_dir(problems: list[Problem]) -> None:
    assert len(problems) == 1
    problem = problems[0]

    skeldir, preserve_symlinks = get_skel_dir(problem.path)

    for d in config.args.directory:
        sources = [skeldir / d, skeldir / d.parent / (d.name + ".template")]
        target = problem.path / d

        if d.is_absolute():
            error(f"{d} is not a relative path.")
            continue

        found = False
        for source in sources:
            if not source.is_file() and not source.is_dir():
                continue

            target.parent.mkdir(exist_ok=True, parents=True)
            copytree_and_substitute(
                source, target, None, exist_ok=True, preserve_symlinks=preserve_symlinks
            )
            found = True
            break

        if not found:
            error(f"{source} does not exist")


# NOTE: This is one of few places that prints to stdout instead of stderr.
def create_gitlab_jobs(contest: str, problems: list[Problem]) -> None:
    git = ShellCommand.get("git")
    if git is None:
        error("git command not found!")
        return

    if not git("rev-parse", "--is-inside-work-tree").startswith("true"):
        error("not inside git")
        return

    git_root_path = Path(git("rev-parse", "--show-toplevel").strip()).absolute()

    def problem_source_dir(problem: Problem) -> Path:
        return problem.path.absolute().relative_to(git_root_path)

    if config.args.latest_bt:
        header_yml = (config.RESOURCES_ROOT / "skel/gitlab_ci/header_latest_bt.yaml").read_text()
    else:
        header_yml = (config.RESOURCES_ROOT / "skel/gitlab_ci/header_docker_bt.yaml").read_text()
    print(header_yml)

    contest_yml = (config.RESOURCES_ROOT / "skel/gitlab_ci/contest.yaml").read_text()
    contest_path = Path(".").absolute().relative_to(git_root_path)
    changes = "".join(
        f"      - {problem_source_dir(problem)}/{pdf_type.path().parent}/**/*\n"
        for problem in problems
        for pdf_type in latex.PdfType
    )
    print(
        substitute(
            contest_yml, {"contest": contest, "contest_path": str(contest_path), "changes": changes}
        )
    )

    problem_yml = (config.RESOURCES_ROOT / "skel/gitlab_ci/problem.yaml").read_text()
    for problem_obj in problems:
        problem_path = problem_source_dir(problem_obj)
        problem = problem_obj.name
        print("\n")
        print(
            substitute(problem_yml, {"problem": problem, "problem_path": str(problem_path)}),
            end="",
        )


def create_forgejo_actions(contest: str, problems: list[Problem]) -> None:
    if Path(".git").is_dir():
        contest_path = Path(".")
        forgejo = Path(".forgejo")
    elif Path("../.git").is_dir():
        contest_path = Path(contest)
        forgejo = Path("../.forgejo")
    else:
        fatal(".git and ../.git not found after changing to contest directory.")

    if config.args.latest_bt:
        src = config.RESOURCES_ROOT / "skel/forgejo_actions_latest_bt"
    else:
        src = config.RESOURCES_ROOT / "skel/forgejo_actions_docker_bt"

    if config.args.latest_bt:
        # Copy the 'setup' action:
        setup_action_source = src / "setup.yaml"
        setup_action_target = forgejo / Path("actions/setup/action.yml")
        setup_action_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(setup_action_source, setup_action_target)

    # Copy the contest-level workflow.
    contest_workflow_source = (src / "contest.yaml").read_text()
    contest_workflow = substitute(
        contest_workflow_source, {"contest": contest, "contest_path": str(contest_path)}
    )
    contest_workflow_target = forgejo / Path(f"workflows/{contest}/_contest.yaml")
    contest_workflow_target.parent.mkdir(parents=True, exist_ok=True)
    contest_workflow_target.write_text(contest_workflow)

    # Copy the problem-level workflows.
    problem_workflow_source = (src / "problem.yaml").read_text()
    for problem_obj in problems:
        problem = problem_obj.name
        problem_path = contest_path / problem
        problem_workflow = substitute(
            problem_workflow_source, {"problem": problem, "problem_path": str(problem_path)}
        )
        problem_workflow_target = forgejo / Path(f"workflows/{contest}/{problem}.yaml")
        problem_workflow_target.parent.mkdir(parents=True, exist_ok=True)
        problem_workflow_target.write_text(problem_workflow)


# Differences with forgejo:
# - flat structure, with all workflows directly in `.github/workflows`.
def create_github_actions(contest: str, problems: list[Problem]) -> None:
    if config.args.latest_bt:
        fatal("Caching the latest BAPCtools is not supported for github actions.")

    if Path(".git").is_dir():
        contest_path = Path(".")
        github = Path(".github")
        nest = False
    elif Path("../.git").is_dir():
        contest_path = Path(contest)
        github = Path("../.github")
        nest = True
    else:
        fatal(".git and ../.git not found after changing to contest directory.")

    # Copy the contest-level workflow.
    contest_workflow_source = (
        config.RESOURCES_ROOT / "skel/forgejo_actions_docker_bt/contest.yaml"
    ).read_text()
    contest_workflow = substitute(
        contest_workflow_source, {"contest": contest, "contest_path": str(contest_path)}
    )
    if nest:
        contest_workflow_target = github / Path(f"workflows/{contest}.yaml")
    else:
        contest_workflow_target = github / Path("workflows/contest.yaml")
    contest_workflow_target.parent.mkdir(parents=True, exist_ok=True)
    contest_workflow_target.write_text(contest_workflow)

    # Copy the problem-level workflows.
    problem_workflow_source = (
        config.RESOURCES_ROOT / "skel/forgejo_actions_docker_bt/problem.yaml"
    ).read_text()
    for problem_obj in problems:
        problem = problem_obj.name
        problem_path = contest_path / problem
        problem_workflow = substitute(
            problem_workflow_source, {"problem": problem, "problem_path": str(problem_path)}
        )
        if nest:
            problem_workflow_target = github / Path(f"workflows/{contest}_{problem}.yaml")
        else:
            problem_workflow_target = github / Path(f"workflows/{problem}.yaml")
        problem_workflow_target.parent.mkdir(parents=True, exist_ok=True)
        problem_workflow_target.write_text(problem_workflow)
