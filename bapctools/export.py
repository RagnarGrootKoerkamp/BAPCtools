import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from bapctools import config
from bapctools.contest import (
    call_api,
    call_api_get_json,
    contest_yaml,
    get_contests,
    get_request_json,
    problems_yaml,
)
from bapctools.latex import PdfType
from bapctools.problem import Problem
from bapctools.util import (
    ask_variable_bool,
    drop_suffix,
    ensure_symlink,
    eprint,
    error,
    fatal,
    glob,
    has_substitute,
    inc_label,
    log,
    normalize_yaml_value,
    PrintBar,
    read_yaml,
    ryaml_filter,
    substitute,
    verbose,
    warn,
    write_yaml,
)
from bapctools.validate import AnswerValidator, InputValidator, OutputValidator
from bapctools.visualize import InputVisualizer, OutputVisualizer


def select_languages(problems: list[Problem]) -> list[str]:
    if config.args.lang:
        languages = config.args.lang
    else:
        languages = list(set(sum((p.statement_languages for p in problems), [])))
    languages.sort()
    if config.args.legacy:
        if len(languages) > 1:
            # legacy can handle at most one language
            fatal("Multiple languages found, please specify one with --lang")
    if not languages:
        fatal("No language found")
    return languages


# Write any .lang.pdf files to .pdf.
def remove_language_pdf_suffix(file: Path, lang: Optional[str]) -> Path:
    if lang and file.name.endswith(f".{lang}.pdf"):
        return file.with_name(file.name.removesuffix(f".{lang}.pdf") + ".pdf")
    else:
        return file


def build_samples_zip(problems: list[Problem], output: Path, languages: list[str]) -> None:
    bar = PrintBar("Zip", len(output.name), item=output)
    bar.log("writing sample zip file")
    zf = zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    # Do not include contest PDF for kattis.
    if not config.args.kattis:
        for language in languages:
            for file in glob(Path("."), f"contest*.{language}.pdf"):
                out = remove_language_pdf_suffix(file, language) if config.args.legacy else file
                if Path(file).is_file():
                    zf.write(
                        file,
                        out,
                        compress_type=zipfile.ZIP_DEFLATED,
                    )

    for problem in problems:
        if not problem.label:
            fatal(f"Cannot create samples zip: Problem {problem.name} does not have a label!")

        outputdir = Path(problem.label)
        zf.writestr(f"{problem.label}/", "", compress_type=zipfile.ZIP_DEFLATED)

        attachments_dir = problem.path / "attachments"
        if (problem.interactive or problem.multi_pass) and not attachments_dir.is_dir():
            bar.error(
                f"{problem.settings.type_name()} problem {problem.name} does not have an attachments/ directory."
            )
            continue

        contents: dict[Path, Path] = {}  # Maps desination to source, to allow checking duplicates.

        # Add samples.
        samples = problem.download_samples()
        for i, (in_file, ans_file) in enumerate(samples):
            base_name = outputdir / str(i + 1)
            contents[base_name.with_suffix(".in")] = in_file
            if ans_file.stat().st_size > 0:
                contents[base_name.with_suffix(".ans")] = ans_file

        # Add attachments if they exist.
        if attachments_dir.is_dir():
            for f in attachments_dir.iterdir():
                if f.is_dir():
                    bar.error(f"{f} directory attachments are not yet supported.")
                elif f.is_file():
                    if f.name.startswith("."):
                        continue  # Skip dotfiles
                    destination = outputdir / f.name
                    if destination in contents:
                        bar.error(
                            f"Cannot overwrite {destination} from attachments/"
                            + f" (sourced from {contents[destination]})."
                            + "\n\tDo not include samples in attachments/,"
                            + " use .{in,ans}.statement or .{in,ans}.download instead."
                        )
                    else:
                        contents[destination] = f
                else:
                    bar.error(f"Cannot include broken file {f}.")

        if contents:
            for destination, source in contents.items():
                zf.write(source, destination)
        else:
            bar.error(f"No attachments or samples found for problem {problem.name}.")

    zf.close()
    bar.log("done")


def build_problem_zip(problem: Problem, output: Path) -> bool:
    """Make DOMjudge/Kattis ZIP file for specified problem."""

    bar = PrintBar("Zip", len(problem.name) + 4, item=problem)

    from ruamel.yaml.comments import CommentedMap

    languages = select_languages([problem])

    files = [
        ("problem.yaml", True),
        ("statement/*", True),
        ("solution/*", False),
        ("problem_slide/*", False),
        ("generators/*", False),
        (f"{InputValidator.source_dir}/**/*", True),
        (f"{AnswerValidator.source_dir}/**/*", False),  # TODO required when not interactive?
        ("submissions/accepted/**/*", True),
        ("submissions/*/**/*", False),
        ("attachments/**/*", problem.interactive or problem.multi_pass),
        (f"{InputVisualizer.source_dir}/**/*", False),
        (f"{OutputVisualizer.source_dir}/**/*", False),
    ]

    # Do not include PDFs for kattis.
    if not config.args.kattis:
        for language in languages:
            files.append((PdfType.PROBLEM.path(language, ".pdf").name, True))
            files.append((PdfType.PROBLEM_SLIDE.path(language, ".pdf").name, False))
            files.append((PdfType.SOLUTION.path(language, ".pdf").name, False))

    if problem.custom_output:
        files.append((f"{OutputValidator.source_dir}/**/*", True))

    bar.log("preparing zip file content")

    # prepare files inside dir
    export_dir = problem.tmpdir / "export"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    # For Kattis / 2025-09 spec, prepend the problem shortname to all files.
    if config.args.kattis or not config.args.legacy:
        export_dir /= problem.name
    export_dir.mkdir(parents=True, exist_ok=True)

    def add_file(path: Path, source: Path) -> None:
        if source.stat().st_size >= config.ICPC_FILE_LIMIT * 1024**2:
            bar.warn(
                f"{path} is too large for the ICPC Archive (limit {config.ICPC_FILE_LIMIT}MiB)!"
            )
        path = export_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_symlink(path, source)

    # Include all files beside testcases
    for pattern, required in files:
        # Only include hidden files if the pattern starts with a '.'.
        paths = list(glob(problem.path, pattern, include_hidden=True))
        if required and len(paths) == 0:
            bar.error(f"No matches for required path {pattern}.")
        for f in paths:
            if f.is_file() and not f.name.startswith("."):
                add_file(f.relative_to(problem.path), f)

    def add_testcase(in_file: Path) -> None:
        base_name = drop_suffix(in_file, [".in", ".in.statement", ".in.download"])
        for ext in config.KNOWN_DATA_EXTENSIONS:
            f = base_name.with_suffix(ext)
            if f.is_file():
                add_file(f.relative_to(problem.path), f)

    # Include all sample test cases and copy all related files.
    samples = problem.download_samples()
    if len(samples) == 0:
        bar.error("No samples found.")
    for in_file, _ in samples:
        add_testcase(in_file)

    # Include all secret test cases and copy all related files.
    pattern = "data/secret/**/*.in"
    paths = glob(problem.path, pattern)
    if len(paths) == 0:
        bar.error(f"No secret test cases found in {pattern}.")
    for f in paths:
        if f.is_file():
            if f.with_suffix(".ans").is_file():
                add_testcase(f)
            else:
                bar.warn(f"No answer file found for {f}, skipping.")

    # handle languages (files and yaml have to be in sync)
    yaml_path = export_dir / "problem.yaml"
    yaml_data = read_yaml(yaml_path)
    assert isinstance(yaml_data, CommentedMap)
    yaml_data["name"] = CommentedMap(
        {language: problem.settings.name[language] for language in languages}
    )
    for type in PdfType:
        for file in export_dir.glob(str(type.path("*"))):
            if file.suffixes[-2][1:] not in languages:
                file.unlink()

    # drop explicit timelimit for kattis
    if config.args.kattis:
        if "limits" in yaml_data and "time_limit" in yaml_data["limits"]:
            ryaml_filter(yaml_data["limits"], "time_limit")

    # substitute constants.
    if problem.settings.constants:
        constants_supported = [
            "data/**/test_group.yaml",
            f"{InputValidator.source_dir}/**/*",
            f"{AnswerValidator.source_dir}/**/*",
            f"{OutputValidator.source_dir}/**/*",
            # "statement/*", "solution/*", "problem_slide/*", use \constant{} commands
            # "submissions/*/**/*", removed support?
            f"{InputVisualizer.source_dir}/**/*",
            f"{OutputVisualizer.source_dir}/**/*",
        ]
        for pattern in constants_supported:
            for f in export_dir.glob(pattern):
                if f.is_file() and has_substitute(f, config.CONSTANT_SUBSTITUTE_REGEX):
                    text = f.read_text()
                    text = substitute(
                        text,
                        problem.settings.constants,
                        pattern=config.CONSTANT_SUBSTITUTE_REGEX,
                        bar=bar,
                    )
                    f.unlink()
                    f.write_text(text)

    bar = bar.start(f"{problem.name}.zip")

    # move pdfs
    if config.args.legacy:
        for type in PdfType:
            file = export_dir / type.path(languages[0], ".pdf").name
            if file.exists():
                file.rename(remove_language_pdf_suffix(file, languages[0]))
    else:
        for language in languages:
            for type in PdfType:
                path = type.path(language, ".pdf")
                file = export_dir / path.name
                out = export_dir / path
                if not file.exists():
                    continue
                if out.exists():
                    bar.warn(f"can't add {path} (already exists).")
                    file.unlink()
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                file.rename(out)

    # downgrade some parts of the problem to be more legacy like
    if config.args.legacy:
        # drop format version -> legacy
        if "problem_format_version" in yaml_data:
            ryaml_filter(yaml_data, "problem_format_version")
        # type -> validation
        if "type" in yaml_data:
            ryaml_filter(yaml_data, "type")
        validation = []
        if problem.custom_output:
            validation.append("custom")
            if problem.interactive:
                validation.append("interactive")
            if problem.multi_pass:
                validation.append("multi-pass")
        else:
            validation.append("default")
        yaml_data["validation"] = " ".join(validation)
        # name is a string, not a map
        yaml_data["name"] = problem.settings.name[languages[0]]
        # credits -> author
        if "credits" in yaml_data:
            ryaml_filter(yaml_data, "credits")
            if problem.settings.credits.authors:
                yaml_data["author"] = ", ".join(p.name for p in problem.settings.credits.authors)
        # change source:
        if problem.settings.source:
            if len(problem.settings.source) > 1:
                bar.warn(f"Found multiple sources, using '{problem.settings.source[0].name}'.")
            yaml_data["source"] = problem.settings.source[0].name
            yaml_data["source_url"] = problem.settings.source[0].url
        # limits.time_multipliers -> time_multiplier / time_safety_margin
        if "limits" not in yaml_data or not yaml_data["limits"]:
            yaml_data["limits"] = CommentedMap()
        limits = yaml_data["limits"]
        if "time_multipliers" in limits:
            ryaml_filter(limits, "time_multipliers")
        limits["time_multiplier"] = problem.limits.ac_to_time_limit
        limits["time_safety_margin"] = problem.limits.time_limit_to_tle
        # drop explicit timelimit
        if "time_limit" in limits:
            ryaml_filter(limits, "time_limit")
        # validator_flags
        validator_flags = " ".join(
            problem.get_test_case_yaml(
                problem.path / "data",
                PrintBar("Zip", item="Getting validator_flags for legacy export"),
            ).output_validator_args
        )
        if validator_flags:
            yaml_data["validator_flags"] = validator_flags

        # The downloadable samples should be copied to attachments/.
        if problem.interactive or problem.multi_pass:
            samples = problem.download_samples()
            for i, (in_file, ans_file) in enumerate(samples):
                base_name = export_dir / "attachments" / str(i + 1)
                add_file(base_name.with_suffix(".in"), in_file)
                if ans_file.stat().st_size > 0:
                    add_file(base_name.with_suffix(".ans"), ans_file)

        # handle time limit
        if not config.args.kattis:
            (export_dir / ".timelimit").write_text(str(problem.limits.time_limit))

        # Replace \problemname{...} by the value of `name:` in problems.yaml in all .tex files.
        for f in (export_dir / "statement").iterdir():
            if f.is_file() and f.suffix == ".tex" and len(f.suffixes) >= 2:
                lang = f.suffixes[-2][1:]
                t = f.read_text()
                match = re.search(r"\\problemname\{\s*(\\problemyamlname)?\s*\}", t)
                if match:
                    if lang in problem.settings.name:
                        t = t.replace(match[0], rf"\problemname{{{problem.settings.name[lang]}}}")
                        f.unlink()
                        f.write_text(t)
                    else:
                        bar.error(f"{f}: no name set for language {lang}.")

        # rename statement dirs
        if (export_dir / "statement").exists():
            (export_dir / "statement").rename(export_dir / "problem_statement")
        for d in ["solution", "problem_slide"]:
            if not (export_dir / d).is_dir():
                continue
            for f in list(glob(problem.path, f"{d}/*")):
                if f.is_file():
                    out = Path("problem_statement") / f.relative_to(problem.path / d)
                    if out.exists():
                        bar.warn(f"Cannot export {f.relative_to(problem.path)} as {out}")
                    else:
                        add_file(out, f)
            shutil.rmtree(export_dir / d)

        # rename output_validator dir
        if (export_dir / OutputValidator.source_dir).exists():
            (export_dir / "output_validators").mkdir(parents=True)
            (export_dir / OutputValidator.source_dir).rename(
                export_dir / "output_validators" / OutputValidator.source_dir
            )

        # rename test_group.yaml back to testdata.yaml
        for f in (export_dir / "data").rglob("test_group.yaml"):
            f.rename(f.with_name("testdata.yaml"))
            # TODO potentially, some keys also need to be renamed, but we don't use this often enough for this to matter (I hope)

    # handle yaml updates
    yaml_path.unlink()
    write_yaml(yaml_data, yaml_path)

    # Build .ZIP file.
    bar.log("writing zip file")
    try:
        zf = zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

        export_dir = problem.tmpdir / "export"
        for f in sorted(export_dir.rglob("*")):
            name = f.relative_to(export_dir)
            if f.is_file():
                zf.write(f, name, compress_type=zipfile.ZIP_DEFLATED)
            if f.is_dir():
                zf.writestr(f"{name}/", "", compress_type=zipfile.ZIP_DEFLATED)

        # Done.
        zf.close()
        bar.log("done")
        eprint()
    except Exception:
        return False

    return True


# Assumes the current working directory has: the zipfiles and
# contest*.{lang}.pdf
# solutions*.{lang}.pdf
# problem-slides*.{lang}.pdf
# Output is <outfile>
def build_contest_zip(
    problems: list[Problem], zipfiles: list[Path], outfile: str, languages: list[str]
) -> None:
    if not config.args.kattis:  # Kattis does not use problems.yaml.
        update_problems_yaml(problems)

    bar = PrintBar("Zip", len(outfile), item=outfile)
    bar.log("writing zip file")

    zf = zipfile.ZipFile(outfile, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    for fname in zipfiles:
        zf.write(fname, fname.name, compress_type=zipfile.ZIP_DEFLATED)

    # For general zip export, also create pdfs and a samples zip.
    if not config.args.kattis:
        sampleout = Path("samples.zip")
        build_samples_zip(problems, sampleout, languages)

        def add_file(file: Path) -> None:
            if file.is_file():
                out = remove_language_pdf_suffix(file, languages[0]) if config.args.legacy else file
                zf.write(
                    file,
                    out,
                    compress_type=zipfile.ZIP_DEFLATED,
                )

        add_file(Path("problems.yaml"))
        add_file(Path("contest.yaml"))
        add_file(sampleout)
        for language in languages:
            for name in [
                *Path(".").glob(f"contest*.{language}.pdf"),
                *Path(".").glob(f"solutions*.{language}.pdf"),
                *Path(".").glob(f"problem-slides*.{language}.pdf"),
            ]:
                add_file(name)

    # For Kattis export, delete the original zipfiles.
    if config.args.kattis:
        for fname in zipfiles:
            fname.unlink()

    zf.close()
    bar.log("done")
    eprint()


def update_contest_id(cid: str) -> None:
    contest_yaml_path = Path("contest.yaml")
    data = read_yaml(contest_yaml_path)
    assert isinstance(data, dict)
    data["contest_id"] = cid
    write_yaml(data, contest_yaml_path)
    log(f"Updated contest_id to {cid}")


def export_contest(cid: Optional[str]) -> str:
    if not contest_yaml().exists:
        fatal("Exporting a contest only works if contest.yaml is available.")

    data = contest_yaml().dict()
    if cid:
        data["id"] = cid

    verbose("Uploading contest.yaml:")
    verbose(data)
    r = call_api(
        "POST",
        "/contests",
        files={
            "yaml": (
                "contest.yaml",
                write_yaml(data),
                "application/x-yaml",
            )
        },
    )
    if r.status_code == 400:
        try:
            fatal(r.json()["message"])
        except Exception:
            fatal(r.text)
    r.raise_for_status()

    new_cid = normalize_yaml_value(get_request_json(r), str)
    assert isinstance(new_cid, str)

    log(f"Uploaded the contest to contest_id {new_cid}.")
    if new_cid != cid:
        if ask_variable_bool("Update contest_id in contest.yaml automatically"):
            update_contest_id(new_cid)

    return new_cid


# Update name and time limit values.
def update_problems_yaml(problems: list[Problem], colors: Optional[list[str]] = None) -> None:
    # Make sure problems.yaml is formatted correctly.
    # We cannot use the resulting `list[ProblemsYamlEntry]`, because we need to edit them.
    # TODO #102 Perhaps there's a way that ProblemsYamlEntry can also be a ruamel.yaml CommentedMap?
    problems_yaml()

    log("Updating problems.yaml")
    path = Path("problems.yaml")
    data = path.is_file() and read_yaml(path) or []
    assert isinstance(data, list)

    change = False
    for problem in problems:
        found = False

        # ProblemSettings always has `name: dict[str, str]`, but we revert to `str` when `--legacy` is used.
        problem_name: str | dict[str, str] = problem.settings.name
        if isinstance(problem_name, dict) and config.args.legacy:
            problem_name = problem_name[select_languages(problems)[0]]

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
            label = "X" if contest_yaml().test_session else "A"
            for d in data:
                d["label"] = label
                label = inc_label(label)

    if config.args.number:
        n = 0
        for d in data:
            n += 1
            newlabel = f"S{n:>02}"
            if d["label"] != newlabel:
                d["label"] = newlabel
                change = True

    if change:
        if config.args.action in ["update_problems_yaml"] or ask_variable_bool(
            "Update problems.yaml with latest values"
        ):
            write_yaml(data, path)
            log("Updated problems.yaml")
    else:
        if config.args.action == "update_problems_yaml":
            log("Already up to date")


def export_problems(problems: list[Problem], cid: str) -> object:
    if not contest_yaml().exists:
        fatal("Exporting a contest only works if contest.yaml is available.")

    update_problems_yaml(problems)

    # Uploading problems.yaml
    verbose("Uploading problems.yaml:")
    data = Path("problems.yaml").read_text()
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
        try:
            fatal(r.json()["message"])
        except Exception:
            fatal(r.text)
    r.raise_for_status()

    log(f"Uploaded problems.yaml for contest_id {cid}.")
    return get_request_json(r)  # Returns the API IDs of the added problems.


# Export a single problem to the specified contest ID.
def export_problem(problem: Problem, cid: str, pid: Optional[str]) -> None:
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
    yaml_response = get_request_json(r)
    if isinstance(yaml_response, dict) and "messages" in yaml_response:
        verbose("RESPONSE:\n" + "\n".join(yaml_response["messages"]))
    elif isinstance(yaml_response, dict) and "message" in yaml_response:
        verbose("RESPONSE: " + yaml_response["message"])
    else:
        verbose("RESPONSE:\n" + r.text)
    r.raise_for_status()


# Export the contest and individual problems to DOMjudge.
# Mimicked from https://github.com/DOMjudge/domjudge/blob/main/misc-tools/import-contest.sh
def export_contest_and_problems(problems: list[Problem], languages: list[str]) -> None:
    if config.args.contest_id:
        cid: Optional[str] = config.args.contest_id
    else:
        cid = contest_yaml().contest_id
        if cid is not None:
            log(f"Reusing contest id {cid} from contest.yaml")
    if not any(contest["id"] == cid for contest in get_contests()):
        cid = export_contest(cid)
    assert cid is not None

    if len(languages) != 1:
        # TODO: fix this
        fatal("DOMjudge does not yet support multiple languages")

    with open(f"contest.{languages[0]}.pdf", "rb") as pdf_file:
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

    def get_problem_id(problem: Problem) -> Optional[str]:
        nonlocal ccs_problems
        for p in ccs_problems:
            if problem.name in [p.get("short_name"), p.get("id"), p.get("externalid")]:
                pid = normalize_yaml_value(p.get("id"), str)
                assert isinstance(pid, str)
                return pid
        return None

    for problem in problems:
        pid = get_problem_id(problem)
        export_problem(problem, cid, pid)


def check_if_user_has_team() -> None:
    # Not using the /users/{uid} route, because {uid} is either numeric or a string depending on the DOMjudge config.
    users = call_api_get_json("/users")
    if not any(user["username"] == config.args.username and user["team"] for user in users):
        warn(f'User "{config.args.username}" is not associated with a team.')
        warn("Therefore, the jury submissions will not be run by the judgehosts.")
        if ask_variable_bool("Continue export to DOMjudge", False):
            fatal("Aborted.")
