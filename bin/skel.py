import shutil
import datetime
import re

# Local imports
import config
from export import force_single_language
from problem import Problem
from util import *
import contest

try:
    import questionary
    from questionary import Validator, ValidationError

    has_questionary = True

    class EmptyValidator(Validator):
        def validate(self, document):
            if len(document.text) == 0:
                raise ValidationError(message="Please enter a value")

except Exception:
    has_questionary = False


def _ask_variable(name, default=None, allow_empty=False):
    while True:
        val = input(f"{name}: ")
        val = default if val == "" else val
        if val != "" or allow_empty:
            return val


def _ask_variable_string(name, default=None, allow_empty=False):
    if has_questionary:
        try:
            validate = None if allow_empty else EmptyValidator
            return questionary.text(
                name + ":", default=default or "", validate=validate
            ).unsafe_ask()
        except KeyboardInterrupt:
            fatal("Running interrupted")
    else:
        text = f" ({default})" if default else ""
        return _ask_variable(name + text, default if default else "", allow_empty)


def _ask_variable_bool(name, default=True):
    if has_questionary:
        try:
            return questionary.confirm(name + "?", default=default, auto_enter=False).unsafe_ask()
        except KeyboardInterrupt:
            fatal("Running interrupted")
    else:
        text = " (Y/n)" if default else " (y/N)"
        return _ask_variable(name + text, "Y" if default else "N").lower()[0] == "y"


def _ask_variable_choice(name, choices, default=None):
    if has_questionary:
        try:
            plain = questionary.Style([("selected", "noreverse")])
            return questionary.select(
                name + ":", choices=choices, default=default, style=plain
            ).unsafe_ask()
        except KeyboardInterrupt:
            fatal("Running interrupted")
    else:
        default = default or choices[0]
        text = f" ({default})" if default else ""
        while True:
            got = _ask_variable(name + text, default if default else "")
            if got in choices:
                return got
            else:
                warn(f"unknown option: {got}")


# Returns the alphanumeric version of a string:
# This reduces it to a string that follows the regex:
# [a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]
def _alpha_num(string):
    s = re.sub(r"[^a-zA-Z0-9_.-]", "", string.lower().replace(" ", "").replace("-", ""))
    while s.startswith("_.-"):
        s = s[1:]
    while s.endswith("_.-"):
        s = s[:-1]
    return s


def new_contest():
    if config.args.contest:
        fatal("--contest does not work for new_contest.")
    if config.args.problem:
        fatal("--problem does not work for new_contest.")

    # Ask for all required infos.
    title = _ask_variable_string("name", config.args.contestname)
    subtitle = _ask_variable_string("subtitle", "", True).replace("_", "-")
    dirname = _ask_variable_string("dirname", _alpha_num(title))
    author = _ask_variable_string("author", f"The {title} jury").replace("_", "-")
    testsession = _ask_variable_bool("testsession", False)
    year = _ask_variable_string("year", str(datetime.datetime.now().year))
    source_url = _ask_variable_string("source url", "", True)
    license = _ask_variable_choice("license", config.KNOWN_LICENSES)
    rights_owner = _ask_variable_string("rights owner", "author")
    title = title.replace("_", "-")

    skeldir = config.TOOLS_ROOT / "skel/contest"
    log(f"Copying {skeldir} to {dirname}.")
    copytree_and_substitute(
        skeldir, Path(dirname), locals(), exist_ok=False, preserve_symlinks=False
    )


def get_skel_dir(target_dir):
    skeldir = config.TOOLS_ROOT / "skel/problem"
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


def new_problem():
    target_dir = Path(".")
    if config.args.contest:
        os.chdir(Path(config.args.contest))
    if config.args.problem:
        fatal("--problem does not work for new_problem.")

    statement_languages = config.args.languages if config.args.languages else ["en"]

    problemname = {
        lang: (
            config.args.problemname
            if config.args.problemname
            else _ask_variable_string(f"problem name ({lang})")
        )
        for lang in statement_languages
    }
    dirname = (
        _alpha_num(config.args.problemname)
        if config.args.problemname
        else _ask_variable_string("dirname", _alpha_num(problemname[statement_languages[0]]))
    )
    author = config.args.author if config.args.author else _ask_variable_string("author")

    output_validator_args = "#output_validator_args:"
    custom_output = False
    if config.args.type:
        problem_type = config.args.type
    else:
        problem_type = _ask_variable_choice(
            "type",
            ["pass-fail", "float", "custom", "interactive", "multi-pass", "interactive multi-pass"],
        )
    # The validation type `float` is not official, it only helps setting the `output_validator_args`.
    if problem_type == "float":
        problem_type = "pass-fail"
        output_validator_args = "output_validator_args: float_tolerance 1e-6"
        log("Using default float tolerance of 1e-6")
    # Since version 2023-07-draft of the spec, the `custom` validation type is no longer explicit.
    # The mere existence of the output_validator(s)/ folder signals non-default output validation.
    if problem_type == "custom":
        custom_output = True
        problem_type = "pass-fail"
    if "interactive" in problem_type or "multi-pass" in problem_type:
        custom_output = True

    # Read settings from the contest-level yaml file.
    variables = contest.contest_yaml() | {
        "problemname": "\n".join(f"  {lang}: {name}" for lang, name in problemname.items()),
        "dirname": dirname,
        "author": author,
        "type": problem_type,
        "output_validator_args": output_validator_args,
        "testdata_yaml_comment": "#" if output_validator_args[0] == "#" else "",
    }

    source_name = _ask_variable_string(
        "source", variables.get("source", variables.get("name", "")), True
    )
    source_url = _ask_variable_string("source url", variables.get("source_url", ""), True)
    variables["source"] = (
        f"source:\n  name: {source_name}\n{'  url: {source_url}' if source_url else '  #url:'}"
    )

    variables["license"] = _ask_variable_choice(
        "license", config.KNOWN_LICENSES, variables.get("license", None)
    )
    variables["rights_owner"] = _ask_variable_string(
        "rights owner", variables.get("rights_owner", "author")
    )
    variables["uuid"] = generate_problem_uuid()

    # Copy tree from the skel directory, next to the contest, if it is found.
    skeldir, preserve_symlinks = get_skel_dir(target_dir)
    log(f"Copying {skeldir} to {target_dir / dirname}.")

    if "2023-07-draft" not in (skeldir / "problem.yaml").read_text():
        fatal(
            "new_problem only supports `skel` directories where `problem.yaml` has `version: 2023-07-draft."
        )

    problems_yaml = target_dir / "problems.yaml"

    if problems_yaml.is_file():
        if has_ryaml:
            data = read_yaml(problems_yaml) or []
            prev_label = data[-1]["label"] if data else None
            next_label = (
                ("X" if contest.contest_yaml().get("testsession") else "A")
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
        else:
            error("ruamel.yaml library not found. Please update problems.yaml manually.")

    copytree_and_substitute(
        skeldir,
        target_dir / dirname,
        variables,
        exist_ok=True,
        preserve_symlinks=preserve_symlinks,
        skip=[skeldir / "output_validators"] if not custom_output else None,
    )

    # Warn about missing problem statement skeletons for non-en languages
    for lang in statement_languages:
        filename = f"problem.{lang}.tex"
        statement_path = target_dir / dirname / "problem_statement" / filename
        if not statement_path.is_file():
            warn(f"No skeleton for {filename} found. Create it manually or update skel/problem.")


def rename_problem(problem):
    if not has_ryaml:
        fatal("ruamel.yaml library not found.")

    newname = {
        lang: (
            config.args.problemname
            if config.args.problemname
            else _ask_variable_string(f"New problem name ({lang})", problem.settings.name[lang])
        )
        for lang in problem.statement_languages
    }
    dirname = (
        _alpha_num(config.args.problemname)
        if config.args.problemname
        else _ask_variable_string("dirname", _alpha_num(newname[problem.statement_languages[0]]))
    )

    shutil.move(problem.name, dirname)

    problem_yaml = Path(dirname) / "problem.yaml"
    data = read_yaml(problem_yaml)
    data["name"] = newname
    write_yaml(data, problem_yaml)

    # DOMjudge does not yet support multilingual problems.yaml files.
    statement_language = force_single_language([problem])
    if isinstance(newname, dict):
        newname = newname[statement_language]

    problems_yaml = Path("problems.yaml")
    if problems_yaml.is_file():
        data = read_yaml(problems_yaml) or []
        prob = next((p for p in data if p["id"] == problem.name), None)
        if prob is not None:
            prob["id"] = dirname
            prob["name"] = newname
            write_yaml(data, problems_yaml)


def copy_skel_dir(problems):
    assert len(problems) == 1
    problem = problems[0]

    skeldir, preserve_symlinks = get_skel_dir(problem.path)

    for d in config.args.directory:
        d = Path(d)
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
def create_gitlab_jobs(contest: str, problems: list[Problem]):
    git_root_path = Path(os.popen("git rev-parse --show-toplevel").read().strip()).resolve()

    def problem_source_dir(problem: Problem):
        return problem.path.resolve().relative_to(git_root_path)

    header_yml = (config.TOOLS_ROOT / "skel/gitlab_ci/header.yaml").read_text()
    print(header_yml)

    contest_yml = (config.TOOLS_ROOT / "skel/gitlab_ci/contest.yaml").read_text()
    contest_path = Path(".").resolve().relative_to(git_root_path)
    changes = "".join(
        "      - " + str(problem_source_dir(problem)) + "/problem_statement/**/*\n"
        for problem in problems
    )
    print(
        substitute(
            contest_yml, {"contest": contest, "contest_path": str(contest_path), "changes": changes}
        )
    )

    problem_yml = (config.TOOLS_ROOT / "skel/gitlab_ci/problem.yaml").read_text()
    for problem_obj in problems:
        problem_path = problem_source_dir(problem_obj)
        problem = problem_obj.name
        print("\n")
        print(
            substitute(problem_yml, {"problem": problem, "problem_path": str(problem_path)}),
            end="",
        )
