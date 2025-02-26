import datetime
import sys
import yaml
import re
import zipfile
import config
import util
from pathlib import Path
from typing import Optional

from contest import *
from problem import Problem


def force_single_language(problems):
    if config.args.languages and len(config.args.languages) == 1:
        statement_language = config.args.languages[0]
    else:
        all_languages = set.union(*(set(p.statement_languages) for p in problems))
        if len(all_languages) > 1:
            fatal("Multiple languages found, please specify one with --language")
        statement_language = all_languages.pop()
    return statement_language


# Write any .lang.pdf files to .pdf.
def remove_language_suffix(fname, statement_language):
    if not statement_language:
        return fname
    out = Path(fname)
    if out.suffixes == ["." + statement_language, ".pdf"]:
        out = out.with_suffix("").with_suffix(".pdf")
    return out


def build_samples_zip(problems, output, statement_language):
    zf = zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    # Do not include contest PDF for kattis.
    if not config.args.kattis:
        for fname in glob(Path("."), f"contest*.{statement_language}.pdf"):
            if Path(fname).is_file():
                zf.write(
                    fname,
                    remove_language_suffix(fname, statement_language),
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    for problem in problems:
        outputdir = Path(problem.label)

        attachments_dir = problem.path / "attachments"
        if (problem.interactive or problem.multi_pass) and not attachments_dir.is_dir():
            interactive = "interactive " if problem.interactive else ""
            multi_pass = "multi-pass " if problem.multi_pass else ""
            util.error(
                f"{interactive}{multi_pass}problem {problem.name} does not have an attachments/ directory."
            )
            continue

        empty = True

        # Add attachments if they exist.
        if attachments_dir.is_dir():
            for f in attachments_dir.iterdir():
                if f.is_dir():
                    util.error(f"{f} directory attachments are not yet supported.")
                elif f.is_file() and f.exists():
                    zf.write(f, outputdir / f.name)
                    empty = False
                else:
                    util.error(f"Cannot include broken file {f}.")

        # Add samples for non-interactive and non-multi-pass problems.
        if not problem.interactive and not problem.multi_pass:
            samples = problem.testcases(only_samples=True)
            if samples:
                for i in range(0, len(samples)):
                    sample = samples[i]
                    basename = outputdir / str(i + 1)
                    zf.write(sample.in_path, basename.with_suffix(".in"))
                    zf.write(sample.ans_path, basename.with_suffix(".ans"))
                    empty = False

        if empty:
            util.error(f"No attachments or samples found for problem {problem.name}.")

    zf.close()
    print("Wrote zip to samples.zip", file=sys.stderr)


def build_problem_zip(problem: Problem, output: Path):
    """Make DOMjudge/Kattis ZIP file for specified problem."""

    # Add problem PDF for only one language to the zip file (note that Kattis export does not include PDF)
    statement_language = None if config.args.kattis else force_single_language([problem])

    files = [
        ("problem.yaml", True),
        ("problem_statement/*", True),
        ("submissions/accepted/**/*", True),
        ("submissions/*/**/*", False),
        ("attachments/**/*", problem.interactive or problem.multi_pass),
    ]

    testcases = [
        ("data/secret/**/*.in", True),
        ("data/sample/**/*.in", not problem.interactive and not problem.multi_pass),
    ]

    if problem.interactive or problem.multi_pass:
        # .interaction files don't need a corresponding .in
        # therefore we can handle them like all other files
        files += [("data/sample/**/*.interaction", False)]

    if not config.args.kattis:
        files += [
            (f"problem.{statement_language}.pdf", True),
            ("data/sample/**/*.in.statement", False),
            ("data/sample/**/*.ans.statement", False),
        ]

    if problem.custom_output:
        files.append(("output_validators/**/*", True))

    if config.args.kattis:
        files.append(("input_validators/**/*", True))

    message("preparing zip file content", "Zip", problem.path, color_type=MessageType.LOG)

    # prepare files inside dir
    export_dir = problem.tmpdir / "export"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    # For Kattis, prepend the problem shortname to all files.
    if config.args.kattis:
        export_dir /= problem.name
    export_dir.mkdir(parents=True, exist_ok=True)

    def add(path, source):
        path = export_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_symlink(path, source)

    # Include all files beside testcases
    for pattern, required in files:
        # Only include hidden files if the pattern starts with a '.'.
        paths = list(util.glob(problem.path, pattern, include_hidden=pattern[0] == "."))
        if required and len(paths) == 0:
            util.error(f"No matches for required path {pattern}.")
        for f in paths:
            # NOTE: Directories are skipped because ZIP only supports files.
            if f.is_file():
                out = f.relative_to(problem.path)
                out = remove_language_suffix(out, statement_language)
                add(out, f)

    # Include all testcases (specified by a .in file) and copy all related files
    for pattern, required in testcases:
        paths = list(util.glob(problem.path, pattern))
        if required and len(paths) == 0:
            util.error(f"No matches for required path {pattern}.")
        for f in paths:
            # NOTE: Directories are skipped because ZIP only supports files.
            if f.is_file():
                if not f.with_suffix(".ans").is_file():
                    util.warn(f"No answer file found for {f}, skipping.")
                else:
                    for ext in config.KNOWN_DATA_EXTENSIONS:
                        f2 = f.with_suffix(ext)
                        if f2.is_file():
                            out = f2.relative_to(problem.path)
                            add(out, f)

    # DOMjudge does not support 'type' in problem.yaml nor 'output_validator_args' in testdata.yaml yet.
    # TODO: Remove this once it does.
    if not config.args.kattis and not problem.settings.is_legacy():
        yaml_path = export_dir / "problem.yaml"
        yaml_data = [yaml_path.read_text(), "\nvalidation:"]
        if problem.custom_output:  # custom_output is also True for interactive and multi-pass
            yaml_data.append(" custom")
            if problem.interactive:
                yaml_data.append(" interactive")
            if problem.multi_pass:
                yaml_data.append(" multi-pass")
        else:
            yaml_data.append(" default")
        yaml_data.append("\n")

        validator_flags = " ".join(
            problem.get_testdata_yaml(
                problem.path / "data",
                "output_validator_args",
                PrintBar("Getting validator_flags for legacy DOMjudge export"),
            )
        )
        if validator_flags:
            yaml_data.append("validator_flags: " + validator_flags + "\n")

        yaml_path.unlink()
        yaml_path.write_text("".join(yaml_data))

    # DOMjudge does not support 'limits.time_limit' in problem.yaml yet.
    # TODO: Remove this once it does.
    if not config.args.kattis:
        (export_dir / ".timelimit").write_text(str(problem.limits.time_limit))

    # Replace \problemname{...} by the value of `name:` in problems.yaml in all .tex files.
    # This is needed because Kattis is currently still running the legacy version of the problem spec,
    # rather than 2023-07-draft.
    for f in (export_dir / "problem_statement").iterdir():
        if f.is_file() and f.suffix == ".tex" and len(f.suffixes) >= 2:
            lang = f.suffixes[-2][1:]
            t = f.read_text()
            match = re.search(r"\\problemname\{\s*(\\problemyamlname)?\s*\}", t)
            if match:
                if lang in problem.settings.name:
                    t = t.replace(match[0], r"\problemname{" + problem.settings.name[lang] + "}")
                    f.unlink()
                    f.write_text(t)
                else:
                    util.error(f"{f}: no name set for language {lang}.")

    # DOMjudge does not support constants.
    # TODO: Remove this if it ever does.
    if problem.settings.constants:
        constants_supported = [
            "data/**/testdata.yaml",
            "output_validators/**/*",
            "input_validators/**/*",
            # "problem_statement/*", uses \constants
            # "submissions/*/**/*", removed support?
        ]
        for pattern in constants_supported:
            for f in export_dir.glob(pattern):
                print(f)
                if f.is_file() and util.has_substitute(f, config.CONSTANT_SUBSTITUTE_REGEX):
                    text = f.read_text()
                    text = util.substitute(
                        text,
                        problem.settings.constants,
                        pattern=config.CONSTANT_SUBSTITUTE_REGEX,
                        bar=util.PrintBar("Zip"),
                    )
                    f.unlink()
                    f.write_text(text)

    # Build .ZIP file.
    message("writing zip file", "Zip", output, color_type=MessageType.LOG)
    try:
        zf = zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

        export_dir = problem.tmpdir / "export"
        for f in sorted(export_dir.rglob("*")):
            if f.is_file():
                name = f.relative_to(export_dir)
                zf.write(f, name, compress_type=zipfile.ZIP_DEFLATED)

        # Done.
        zf.close()
        message("done", "Zip", color_type=MessageType.LOG)
        print(file=sys.stderr)
    except Exception:
        return False

    return True


# Assumes the current working directory has: the zipfiles and
# contest*.{lang}.pdf
# solutions*.{lang}.pdf
# Output is <outfile>
def build_contest_zip(problems, zipfiles, outfile, statement_language):
    print(f"writing ZIP file {outfile}", file=sys.stderr)

    if not config.args.kattis:  # Kattis does not use problems.yaml.
        update_problems_yaml(problems)

    zf = zipfile.ZipFile(outfile, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    for fname in zipfiles:
        zf.write(fname, fname.name, compress_type=zipfile.ZIP_DEFLATED)

    # For general zip export, also create pdfs and a samples zip.
    if not config.args.kattis:
        sampleout = Path("samples.zip")
        build_samples_zip(problems, sampleout, statement_language)

        for fname in (
            [
                "problems.yaml",
                "contest.yaml",
                sampleout,
            ]
            + list(Path(".").glob(f"contest*.{statement_language}.pdf"))
            + list(Path(".").glob(f"solutions*.{statement_language}.pdf"))
            + list(Path(".").glob(f"problem-slides*.{statement_language}.pdf"))
        ):
            if Path(fname).is_file():
                zf.write(
                    fname,
                    remove_language_suffix(fname, statement_language),
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    # For Kattis export, delete the original zipfiles.
    if config.args.kattis:
        for fname in zipfiles:
            fname.unlink()

    print("done", file=sys.stderr)
    print(file=sys.stderr)

    zf.close()


def update_contest_id(cid):
    if has_ryaml:
        contest_yaml_path = Path("contest.yaml")
        data = read_yaml(contest_yaml_path)
        data["contest_id"] = cid
        write_yaml(data, contest_yaml_path)
    else:
        error("ruamel.yaml library not found. Update the id manually.")


def export_contest(cid: Optional[str]):
    data = contest_yaml()

    if not data:
        fatal("Exporting a contest only works if contest.yaml is available and not empty.")

    if cid:
        data["id"] = cid

    data["start_time"] = data["start_time"].isoformat()
    if "+" not in data["start_time"]:
        data["start_time"] += "+00:00"
    if not has_ryaml:
        for key in ("duration", "scoreboard_freeze_duration"):
            if key in data:
                # YAML 1.1 parses 1:00:00 as 3600. Convert it back to a string if so.
                # (YAML 1.2 and ruamel.yaml parse it as a string.)
                if isinstance(data[key], int):
                    data[key] = str(datetime.timedelta(seconds=data[key]))

    verbose("Uploading contest.yaml:")
    verbose(data)
    r = call_api(
        "POST",
        "/contests",
        files={
            "yaml": (
                "contest.yaml",
                yaml.dump(data),
                "application/x-yaml",
            )
        },
    )
    if r.status_code == 400:
        fatal(parse_yaml(r.text)["message"])
    r.raise_for_status()

    new_cid = yaml.load(r.text, Loader=yaml.SafeLoader)
    log(f"Uploaded the contest to contest_id {new_cid}.")
    if new_cid != cid:
        log("Update contest_id in contest.yaml automatically? [Y/n]")
        a = input().lower()
        if a == "" or a[0] == "y":
            update_contest_id(new_cid)
            log(f"Updated contest_id to {new_cid}")

    return new_cid


def update_problems_yaml(problems, colors=None):
    # Update name and time limit values.
    if not has_ryaml:
        log(
            "ruamel.yaml library not found. Make sure to update the name and time limit fields manually."
        )
        return

    log("Updating problems.yaml")
    path = Path("problems.yaml")
    data = path.is_file() and read_yaml(path) or []

    # DOMjudge does not yet support multilingual problems.yaml files.
    statement_language = force_single_language(problems)

    change = False
    for problem in problems:
        found = False

        problem_name = problem.settings.name
        if isinstance(problem_name, dict):
            problem_name = problem_name[statement_language]

        for d in data:
            if d["id"] == problem.name:
                found = True
                if problem_name != d.get("name"):
                    change = True
                    d["name"] = problem_name

                if "rgb" not in d:
                    change = True
                    d["rgb"] = "#000000"

                if not problem.limits.time_limit_is_default and problem.limits.time_limit != d.get(
                    "time_limit"
                ):
                    change = True
                    d["time_limit"] = problem.limits.time_limit
                break
        if not found:
            change = True
            log(f"Add problem {problem.name}")
            data.append(
                {
                    "id": problem.name,
                    "label": problem.label,
                    "name": problem_name,
                    "rgb": "#000000",
                    "time_limit": problem.limits.time_limit,
                }
            )

    if colors:
        if len(data) != len(colors):
            warn(
                f"Number of colors ({len(colors)}) is not equal to the number of problems ({len(data)})"
            )
        for d, c in zip(data, colors):
            color = ("" if c.startswith("#") else "#") + c
            if "rgb" not in d or d["rgb"] != color:
                change = True
            d["rgb"] = color

    if config.args.sort:
        sorted_data = sorted(data, key=lambda d: d["id"])
        if data != sorted_data:
            change = True
            data = sorted_data
            label = "X" if contest_yaml().get("testsession") else "A"
            for d in data:
                d["label"] = label
                label = inc_label(label)

    if change:
        if config.args.action in ["update_problems_yaml"]:
            a = "y"
        else:
            log("Update problems.yaml with latest values? [Y/n]")
            a = input().lower()
        if a == "" or a[0] == "y":
            write_yaml(data, path)
            log("Updated problems.yaml")
    else:
        if config.args.action == "update_problems_yaml":
            log("Already up to date")


def export_problems(problems, cid):
    if not contest_yaml():
        fatal("Exporting a contest only works if contest.yaml is available and not empty.")

    update_problems_yaml(problems)

    # Uploading problems.yaml
    with open("problems.yaml", "r") as file:
        data = "".join(file.readlines())
    verbose("Uploading problems.yaml:")
    verbose(data)
    r = call_api(
        "POST",
        f"/contests/{cid}/problems/add-data",
        files={
            "data": (
                "problems.yaml",
                data,
                "application/x-yaml",
            )
        },
    )
    if r.status_code == 400:
        fatal(parse_yaml(r.text)["message"])
    r.raise_for_status()

    log(f"Uploaded problems.yaml for contest_id {cid}.")
    data = yaml.load(r.text, Loader=yaml.SafeLoader)
    return data  # Returns the API IDs of the added problems.


# Export a single problem to the specified contest ID.
def export_problem(problem, cid, pid):
    if pid:
        log(f"Export {problem.name} to id {pid}")
    else:
        log(f"Export {problem.name} to new id")

    zip_path = problem.path / f"{problem.name}.zip"
    if not zip_path.is_file():
        error(f"Did not find {zip_path}. First run `bt zip`.")
        return
    data = None if pid is None else {"problem": pid}
    with zip_path.open("rb") as zipfile:
        r = call_api(
            "POST",
            f"/contests/{cid}/problems",
            data=data,
            files=[("zip", zipfile)],
        )
    yaml_response = yaml.load(r.text, Loader=yaml.SafeLoader)
    if "messages" in yaml_response:
        verbose("RESPONSE:\n" + "\n".join(yaml_response["messages"]))
    elif "message" in yaml_response:
        verbose("RESPONSE: " + yaml_response["message"])
    else:
        verbose("RESPONSE:\n" + str(yaml_response))
    r.raise_for_status()


# Export the contest and individual problems to DOMjudge.
# Mimicked from https://github.com/DOMjudge/domjudge/blob/main/misc-tools/import-contest.sh
def export_contest_and_problems(problems, statement_language):
    if config.args.contest_id:
        cid = config.args.contest_id
    else:
        cid = contest_yaml().get("contest_id")
        if cid is not None and cid != "":
            log(f"Reusing contest id {cid} from contest.yaml")
    if not any(contest["id"] == cid for contest in get_contests()):
        cid = export_contest(cid)

    with open(f"contest.{statement_language}.pdf", "rb") as pdf_file:
        r = call_api(
            "POST",
            f"/contests/{cid}/problemset",
            files={"problemset": ("contest.pdf", pdf_file, "application/pdf")},
        )
    if r.status_code == 404:
        log("Your DOMjudge does not support contest.pdf. Skipping.")
    else:
        r.raise_for_status()
        log("Uploaded contest.pdf.")

    # Query the internal DOMjudge problem IDs.
    ccs_problems = call_api_get_json(f"/contests/{cid}/problems")
    if not ccs_problems:
        export_problems(problems, cid)
        # Need to query the API again, because `/problems/add-data` returns a list of IDs, not the full problem objects.
        ccs_problems = call_api_get_json(f"/contests/{cid}/problems")

    check_if_user_has_team()

    def get_problem_id(problem):
        nonlocal ccs_problems
        for p in ccs_problems:
            if problem.name in [p.get("short_name"), p.get("id"), p.get("externalid")]:
                return p["id"]

    for problem in problems:
        pid = get_problem_id(problem)
        export_problem(problem, cid, pid)


def check_if_user_has_team():
    # Not using the /users/{uid} route, because {uid} is either numeric or a string depending on the DOMjudge config.
    users = call_api_get_json("/users")
    if not any(user["username"] == config.args.username and user["team"] for user in users):
        warn(f'User "{config.args.username}" is not associated with a team.')
        warn("Therefore, the jury submissions will not be run by the judgehosts.")
        log("Continue export to DOMjudge? [N/y]")
        a = input().lower()
        if not a or a[0] != "y":
            fatal("Aborted.")
