# Subcommands for building problem pdfs from the latex source.

import os
import re
import shutil
from enum import Enum
from pathlib import Path
from typing import Final, Optional, TextIO, TYPE_CHECKING

from colorama import Fore, Style

from bapctools import config
from bapctools.contest import contest_yaml, problems_yaml
from bapctools.util import (
    copy_and_substitute,
    ensure_symlink,
    eprint,
    exec_command,
    ExecResult,
    fatal,
    PrintBar,
    substitute,
    tail,
    warn,
)

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools.problem import Problem


class PdfType(Enum):
    PROBLEM = Path("statement") / "problem"
    PROBLEM_SLIDE = Path("problem_slide") / "problem-slide"
    SOLUTION = Path("solution") / "solution"

    def path(self, lang: Optional[str] = None, ext: str = ".tex") -> Path:
        lang = f".{lang}" if lang is not None else ""
        return self.value.with_name(f"{self.value.name}{lang}{ext}")


def latex_builddir(problem: "Problem", language: str) -> Path:
    builddir = problem.tmpdir / "latex" / language
    builddir.mkdir(parents=True, exist_ok=True)
    return builddir


def create_samples_file(problem: "Problem", language: str) -> None:
    builddir = latex_builddir(problem, language)

    # create the samples.tex file
    # For samples, find all .in/.ans/.interaction pairs.
    samples = problem.statement_samples()

    samples_file_path = builddir / "samples.tex"

    if not samples:
        warn(f"Didn't find any statement samples for {problem.name}")
        samples_file_path.write_text("")
        return

    def build_sample_command(content: str) -> str:
        return f"\\expandafter\\def\\csname Sample{i + 1}\\endcsname{{{content}}}\n"

    samples_data = []
    fallback_call = []
    for i, sample in enumerate(samples):
        fallback_call.append(f"\t\\csname Sample{i + 1}\\endcsname\n")

        current_sample = []
        if isinstance(sample, Path):
            assert sample.suffix == ".interaction"
            sample_name = sample.with_suffix("").name
            if problem.interactive:
                interaction_dir = builddir / "interaction"
                interaction_dir.mkdir(exist_ok=True)

                current_sample.append("\\InteractiveSampleHeading\n")
                lines = sample.read_text()
                last = "x"
                cur = ""

                interaction_id = 0
                pass_id = 1

                def flush() -> None:
                    assert last in "<>"
                    nonlocal current_sample, interaction_id

                    interaction_file = interaction_dir / f"{sample_name}-{interaction_id:02}"
                    interaction_file.write_text(cur)

                    mode = "InteractiveRead" if last == "<" else "InteractiveWrite"
                    current_sample.append(f"\\{mode}{{{interaction_file.as_posix()}}}\n")
                    interaction_id += 1

                for line in lines.splitlines():
                    if line == "---":
                        pass_id += 1
                        flush()
                        last = "x"
                        cur = ""
                        current_sample.append(f"\\InteractivePass{{{pass_id}}}")
                    elif line[0] == last:
                        cur += line[1:] + "\n"
                    else:
                        if cur:
                            flush()
                        cur = line[1:] + "\n"
                        last = line[0]
                flush()
            else:
                assert problem.multi_pass

                multi_pass_dir = builddir / "multi_pass"
                multi_pass_dir.mkdir(exist_ok=True)

                lines = sample.read_text()
                last = "<"
                cur_in = ""
                cur_out = ""

                pass_id = 1

                current_sample.append("\\MultipassSampleHeading{}\n")

                def flush() -> None:
                    nonlocal current_sample

                    in_path = multi_pass_dir / f"{sample_name}-{pass_id:02}.in"
                    out_path = multi_pass_dir / f"{sample_name}-{pass_id:02}.out"
                    in_path.write_text(cur_in)
                    out_path.write_text(cur_out)

                    current_sample.append(
                        f"\\SamplePass{{{pass_id}}}{{{in_path.as_posix()}}}{{{out_path.as_posix()}}}\n"
                    )

                for line in lines.splitlines():
                    if line == "---":
                        flush()
                        pass_id += 1
                        last = "<"
                        cur_in = ""
                        cur_out = ""
                    else:
                        if line[0] == "<":
                            assert last == "<"
                            cur_in += line[1:] + "\n"
                        else:
                            assert line[0] == ">"
                            cur_out += line[1:] + "\n"
                            last = ">"
                flush()
        else:
            (in_path, ans_path) = sample
            current_sample = [f"\\Sample{{{in_path.as_posix()}}}{{{ans_path.as_posix()}}}"]
        samples_data.append(build_sample_command("".join(current_sample)))

    # This is only for backwards compatibility in case other people use the generated samples.tex
    # but not the bapc.cls. If remainingsamples is implemented we expect that the class is up to
    # date and does not need the legacy fallback
    samples_data += [
        "% this is only for backwards compatibility\n",
        "\\ifcsname remainingsamples\\endcsname\\else\n",
        "".join(fallback_call),
        "\\fi\n",
    ]

    samples_file_path.write_text("".join(samples_data))


def create_constants_file(problem: "Problem", language: str) -> None:
    constant_data: list[str] = []
    for key, item in problem.settings.constants.items():
        constant_data.append(f"\\expandafter\\def\\csname constants_{key}\\endcsname{{{item}}}\n")

    builddir = latex_builddir(problem, language)
    constants_file_path = builddir / "constants.tex"
    constants_file_path.write_text("".join(constant_data))


# Steps needed for both problem and contest compilation.
def prepare_problem(problem: "Problem", language: str) -> None:
    create_samples_file(problem, language)
    create_constants_file(problem, language)


def get_raw_tl(problem: "Problem") -> str:
    if contest_yaml().print_time_limit is not None:
        print_tl = contest_yaml().print_time_limit
    else:
        print_tl = not config.args.no_time_limit

    if not print_tl:
        return ""
    tl = problem.limits.time_limit
    tl = int(tl) if abs(tl - int(tl)) < 0.0001 else tl
    return str(tl)


def problem_data(problem: "Problem", language: str) -> dict[str, Optional[str]]:
    background = next(
        (p.rgb for p in problems_yaml() if p.id == str(problem.path) and p.rgb), "ffffff"
    )
    # Source: https://github.com/DOMjudge/domjudge/blob/095854650facda41dbb40966e70199840b887e33/webapp/src/Twig/TwigExtension.php#L1056
    background_rgb = [int(background[i : i + 2], 16) for i in [0, 2, 4]]
    foreground = "000000" if sum(background_rgb) > 450 else "ffffff"
    border = "".join(f"{max(0, color - 64):02x}" for color in background_rgb)

    return {
        "problemlabel": problem.label,
        "problemyamlname": problem.settings.name[language].replace("_", " "),
        "problemauthor": ", ".join(a.name for a in problem.settings.credits.authors),
        "problembackground": background,
        "problemforeground": foreground,
        "problemborder": border,
        "timelimit": get_raw_tl(problem),
        "problemdir": problem.path.absolute().as_posix(),
        "problemdirname": problem.name,
        "builddir": latex_builddir(problem, language).as_posix(),
    }


def make_environment(builddir: Path) -> dict[str, str]:
    env = os.environ.copy()
    # Search the contest directory and the latex directory.
    cwd = Path.cwd().absolute()
    latex_paths = [
        builddir.absolute(),
        cwd,
        cwd / "solve_stats",
        cwd / "solve_stats" / "activity",
        cwd / "latex",
        config.RESOURCES_ROOT / "latex",
        # The default empty element at the end makes sure that the new TEXINPUTS ends with a path separator.
        # This is required to make LaTeX look in the default global paths: https://tex.stackexchange.com/a/410353
        env.get("TEXINPUTS", ""),
    ]
    texinputs = os.pathsep.join(map(str, latex_paths))
    if config.args.verbose >= 2:
        eprint(f"export TEXINPUTS='{texinputs}'")
    env["TEXINPUTS"] = texinputs
    return env


TEX_MAGIC_REGEX: Final[str] = "^%\\ ?!tex\\s+program\\s*=\\s*(.*)$"
COMPILED_TEX_MAGIC_REGEX: Final[re.Pattern[str]] = re.compile(TEX_MAGIC_REGEX, re.IGNORECASE)


def get_tex_command(tex_path: Path, bar: PrintBar) -> tuple[str, str]:
    command = config.args.tex_command
    if command is None and tex_path.is_file():
        # try to guess the right tex command from a magic comment
        # https://tex.stackexchange.com/tags/magic-comment/info
        try:
            with tex_path.open() as f:
                for line in f:
                    match = COMPILED_TEX_MAGIC_REGEX.match(line)
                    if match:
                        command = match.group(1).strip()
                        break
        except UnicodeDecodeError:
            pass
    if command is None:
        command = "pdflatex"

    short_name = {
        "pdflatex": "pdf",
        "lualatex": "pdflua",
        "xelatex": "pdfxe",
    }
    if command not in short_name:
        bar.fatal(f"unknwon latex command {command}!")

    if shutil.which(command) is None:
        bar.fatal(f"{command} not found!")

    return (short_name[command], command)


def build_latex_pdf(
    builddir: Path,
    tex_path: Path,
    language: str,
    bar: PrintBar,
    problem_path: Optional[Path] = None,
) -> bool:
    if shutil.which("latexmk") is None:
        bar.fatal("latexmk not found!")

    env = make_environment(builddir)

    logfile = (builddir / tex_path.name).with_suffix(".log")
    built_pdf = (builddir / tex_path.name).with_suffix(".pdf")
    output_pdf = Path(built_pdf.name).with_suffix(f".{language}.pdf")
    dest_path = output_pdf if problem_path is None else problem_path / output_pdf
    short_command, command = get_tex_command(tex_path, bar)

    latexmk_command: list[str | Path] = [
        "latexmk",
        "-cd",
        "-g",
        f'-usepretex="\\\\newcommand\\\\lang{{{language}}}"',
        f"-{short_command}",
        # %P passes the pretex to pdflatex.
        # %O makes sure other default options (like the working directory) are passed correctly.
        # See https://texdoc.org/serve/latexmk/0
        f"-{command}={command} -interaction=nonstopmode -halt-on-error %O %P",
        f"-aux-directory={builddir.absolute()}",
    ]

    eoptions = []
    pipe = True

    if config.args.watch:
        latexmk_command.append("-pvc")
        if config.args.open is None:
            latexmk_command.append("-view=none")
        # write pdf directly in the problem folder
        dest_path.unlink(True)
        latexmk_command.append(f"--jobname={tex_path.stem}.{language}")
        latexmk_command.append(f"-output-directory={dest_path.parent.absolute()}")
        if not config.args.error:
            latexmk_command.append("--silent")
        pipe = False
    else:
        latexmk_command.append(f"-output-directory={builddir.absolute()}")
        if config.args.open is not None:
            latexmk_command.append("-pv")
    if isinstance(config.args.open, Path):
        if shutil.which(f"{config.args.open}") is None:
            bar.warn(f"'{config.args.open}' not found. Using latexmk fallback.")
            config.args.open = True
        else:
            eoptions.append(f"$pdf_previewer = 'start {config.args.open} %O %S';")

    if getattr(config.args, "1"):
        eoptions.append("$max_repeat=1;")

    if eoptions:
        latexmk_command.extend(["-e", "".join(eoptions)])

    latexmk_command.append(tex_path.absolute())

    def run_latexmk(stdout: Optional[TextIO], stderr: Optional[TextIO]) -> ExecResult:
        logfile.unlink(True)
        return exec_command(
            latexmk_command,
            crop=False,
            preexec_fn=False,  # firefox and chrome crash with preexec_fn...
            cwd=builddir,
            stdout=stdout,
            stderr=stderr,
            env=env,
            timeout=None,
        )

    if pipe:
        # use files instead of subprocess.PIPE since later might hang
        outfile = (builddir / tex_path.name).with_suffix(".stdout")
        errfile = (builddir / tex_path.name).with_suffix(".stderr")
        with outfile.open("w") as stdout, errfile.open("w") as stderr:
            ret = run_latexmk(stdout, stderr)
        ret.err = errfile.read_text(errors="replace")  # not used
        ret.out = outfile.read_text(errors="replace")

        last = ret.out
        if not config.args.error:
            last = tail(ret.out, 25)
        if last != ret.out:
            last = f"{last}{Fore.YELLOW}Use -e to show more or see:{Style.RESET_ALL}\n{outfile}"
        ret.out = last
    else:
        ret = run_latexmk(None, None)

    if not ret.status:
        bar.error("Failure compiling PDF:")
        if ret.out is not None:
            eprint(ret.out)
            if logfile.exists():
                eprint(logfile)
        bar.error(f"return code {ret.returncode}")
        bar.error(f"duration {ret.duration}\n")
        return False

    assert not config.args.watch
    ensure_symlink(dest_path, built_pdf, True)

    bar.log(f"PDF written to {dest_path}\n")
    return True


# 1. Copy the latex/problem.tex file to tmpdir/<problem>/latex/<language>/problem.tex,
#    substituting variables.
# 2. Create tmpdir/<problem>/latex/<language>/{samples,constants}.tex.
# 3. Run latexmk and link the resulting <build_type>.<language>.pdf into the problem directory.
def build_problem_pdf(
    problem: "Problem", language: str, build_type: PdfType = PdfType.PROBLEM, web: bool = False
) -> bool:
    """
    Arguments:
    -- language: str, the two-letter language code appearing the file name, such as problem.en.tex
    """
    main_file = build_type.path(ext="-web.tex" if web else ".tex").name

    bar = PrintBar(f"{main_file[:-4]}.{language}.pdf")
    bar.log(f"Building PDF for language {language}")

    prepare_problem(problem, language)

    builddir = latex_builddir(problem, language)

    local_data = Path(main_file)
    copy_and_substitute(
        local_data if local_data.is_file() else config.RESOURCES_ROOT / "latex" / main_file,
        builddir / main_file,
        problem_data(problem, language),
        bar=bar,
    )

    return build_latex_pdf(builddir, builddir / main_file, language, bar, problem.path)


def build_problem_pdfs(
    problem: "Problem", build_type: PdfType = PdfType.PROBLEM, web: bool = False
) -> bool:
    """Build PDFs for various languages. If list of languages is specified,
    (either via config files or --lang arguments), build those. Otherwise
    build all languages for which there is a statement latex source.
    """
    bar = PrintBar(problem.name)
    if config.args.lang is not None:
        for lang in config.args.lang:
            if lang not in problem.statement_languages:
                bar.fatal(f"No statement source for language {lang}")
        languages = config.args.lang
    else:
        languages = problem.statement_languages
        # For solutions or problem slides, filter for `<build_type>.<lang>.tex` files that exist.
        if build_type != PdfType.PROBLEM:
            filtered_languages = []
            for lang in languages:
                if (problem.path / build_type.path(lang)).exists():
                    filtered_languages.append(lang)
                else:
                    bar.warn(f"{build_type.path(lang)} not found")
            languages = filtered_languages
    if config.args.watch and len(languages) > 1:
        fatal("--watch does not work with multiple languages. Please use --lang")
    return all([build_problem_pdf(problem, lang, build_type, web) for lang in languages])


def find_logo() -> Path:
    for directory in ["", "../"]:
        for extension in ["pdf", "png", "jpg"]:
            logo = Path(directory + "logo." + extension)
            if logo.exists():
                return logo
    return config.RESOURCES_ROOT / "latex" / "images" / "logo-not-found.pdf"


def build_contest_pdf(
    contest: str,
    problems: list["Problem"],
    tmpdir: Path,
    language: str,
    build_type: PdfType = PdfType.PROBLEM,
    web: bool = False,
) -> bool:
    builddir = tmpdir / contest / "latex" / language
    builddir.mkdir(parents=True, exist_ok=True)

    problem_slides = build_type == PdfType.PROBLEM_SLIDE
    solutions = build_type == PdfType.SOLUTION

    main_file = "problem-slides" if problem_slides else "solutions" if solutions else "contest"
    main_file += "-web.tex" if web else ".tex"

    bar = PrintBar(f"{main_file[:-3]}{language}.pdf")
    bar.log(f"Building PDF for language {language}")

    config_data = {
        "title": "TITLE",
        "subtitle": "",
        "year": "YEAR",
        "author": "AUTHOR",
        "test_session": "",
        **contest_yaml().dict(),
    }
    config_data["test_session"] = "\\testsession" if config_data.get("test_session") else ""
    config_data["logofile"] = find_logo().as_posix()

    local_contest_data = Path("contest_data.tex")
    copy_and_substitute(
        (
            local_contest_data
            if local_contest_data.is_file()
            else config.RESOURCES_ROOT / "latex" / "contest_data.tex"
        ),
        builddir / "contest_data.tex",
        config_data,
        bar=bar,
    )

    problems_data = ""

    if solutions:
        # include a header slide in the solutions PDF
        headerlangtex = Path(f"solution_header.{language}.tex")
        headertex = Path("solution_header.tex")
        if headerlangtex.exists():
            problems_data += f"\\input{{{headerlangtex}}}\n"
        elif headertex.exists():
            problems_data += f"\\input{{{headertex}}}\n"

    local_per_problem_data = Path(f"contest-{build_type.path().name}")
    per_problem_data_tex = (
        local_per_problem_data
        if local_per_problem_data.is_file()
        else config.RESOURCES_ROOT / "latex" / local_per_problem_data.name
    ).read_text()

    for prob in problems:
        if build_type == PdfType.PROBLEM:
            prepare_problem(prob, language)
        else:  # i.e. for SOLUTION and PROBLEM_SLIDE
            create_constants_file(prob, language)
            tex_no_lang = prob.path / build_type.path()
            tex_with_lang = prob.path / build_type.path(language)
            if tex_with_lang.is_file():
                # All is good
                pass
            elif tex_no_lang.is_file():
                bar.warn(
                    f"Rename {tex_no_lang.name} to {tex_with_lang.name}",
                    prob.name,
                )
                continue
            else:
                bar.warn(f"{tex_with_lang.name} not found", prob.name)
                continue

        problems_data += substitute(
            per_problem_data_tex,
            problem_data(prob, language),
            bar=bar,
        )

    if solutions:
        # include a footer slide in the solutions PDF
        footerlangtex = Path(f"solution_footer.{language}.tex")
        footertex = Path("solution_footer.tex")
        if footerlangtex.exists():
            problems_data += f"\\input{{{footerlangtex}}}\n"
        elif footertex.exists():
            problems_data += f"\\input{{{footertex}}}\n"

    (builddir / f"contest-{build_type.path(ext='s.tex').name}").write_text(problems_data)

    return build_latex_pdf(builddir, Path(main_file), language, bar)


def build_contest_pdfs(
    contest: str,
    problems: list["Problem"],
    tmpdir: Path,
    lang: Optional[str] = None,
    build_type: PdfType = PdfType.PROBLEM,
    web: bool = False,
) -> bool:
    if lang:
        return build_contest_pdf(contest, problems, tmpdir, lang, build_type, web)

    bar = PrintBar(contest)
    """Build contest PDFs for all available languages"""
    statement_languages = set.intersection(*(set(p.statement_languages) for p in problems))
    if not statement_languages:
        bar.fatal("No statement language present in every problem.")
    if config.args.lang is not None:
        languages = set(config.args.lang)
        for lang in languages - statement_languages:
            bar.fatal(f"Unable to build all statements for language {lang}")
    else:
        languages = statement_languages
    if config.args.watch and len(languages) > 1:
        bar.fatal("--watch does not work with multiple languages. Please use --lang")
    return all(
        build_contest_pdf(contest, problems, tmpdir, lang, build_type, web) for lang in languages
    )


def get_argument_for_command(texfile: TextIO, command: str) -> Optional[str]:
    """Return the (whitespace-normalised) argument for the given command in the given texfile.
    If texfile contains `\foo{bar  baz }`, returns the string 'bar baz'.
    The command is given without backslash.


    Assumptions:
    the command and its argument are on the same line,
    and that the argument contains no closing curly brackets.
    """

    for line in texfile:
        regex = r"\\" + command + r"\{(.*)\}"
        match = re.search(regex, line)
        if match:
            return " ".join(match.group(1).split())
    return None
