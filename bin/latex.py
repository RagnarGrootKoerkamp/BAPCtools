# Subcommands for building problem pdfs from the latex source.

import os
import util
import re
import subprocess
import tempfile
import sys
from pathlib import Path

import config
import util
from util import *
from contest import *


def create_samples_file(problem):
    builddir = problem.tmpdir

    # create the samples.tex file
    # For samples, find all .in/.ans/.interaction pairs.
    samples = problem.testcases(
        needans=not problem.interactive,
        needinteraction=problem.interactive,
        only_sample=True,
        statement_samples=True,
        copy=True,
    )
    if samples is False:
        samples = []

    # For interactive problems, find all .interaction files instead.
    samples += glob(problem.path / 'data' / 'sample', '*.interaction')
    samples_file_path = builddir / 'samples.tex'

    if samples is []:
        samples_file_path.write_text('')
        return

    samples_data = ''

    for sample in samples:
        if isinstance(sample, Path) and sample.suffix == '.interaction':
            interaction_dir = builddir / 'interaction'
            interaction_dir.mkdir(exist_ok=True)

            samples_data += '\\InteractiveSampleHeading\n'
            lines = sample.read_text()
            last = 'x'
            cur = ''

            interaction_id = 0

            def flush():
                assert last in '<>'
                nonlocal samples_data, interaction_id

                interaction_file = (
                    interaction_dir / f'{sample.with_suffix("").name}-{interaction_id:02}'
                )
                interaction_file.write_text(cur)

                mode = 'InteractiveRead' if last == '<' else 'InteractiveWrite'
                samples_data += f'\\{mode}{{{interaction_file.as_posix()}}}\n'
                interaction_id += 1

            for line in lines.splitlines():
                if line[0] == last:
                    cur += line[1:] + '\n'
                else:
                    if cur:
                        flush()
                    cur = line[1:] + '\n'
                    last = line[0]
            flush()
        else:
            # Already handled above.
            if sample.in_path.with_suffix('.interaction').is_file():
                continue
            samples_data += (
                f'\\Sample{{{sample.in_path.as_posix()}}}{{{sample.ans_path.as_posix()}}}\n'
            )
    samples_file_path.write_text(samples_data)


# Steps needed for both problem and contest compilation.
def prepare_problem(problem):
    builddir = problem.tmpdir
    builddir.mkdir(exist_ok=True)

    create_samples_file(problem)


def get_tl(problem):
    problem_config = problem.settings
    tl = problem_config.timelimit
    tl = int(tl) if abs(tl - int(tl)) < 0.0001 else tl

    if 'print_timelimit' in contest_yaml():
        print_tl = contest_yaml()['print_timelimit']
    else:
        print_tl = not config.args.no_timelimit

    return tl if print_tl else ''


def make_environment():
    env = os.environ.copy()
    # Search the contest directory and the latex directory.
    latex_paths = [
        Path.cwd(),
        Path.cwd() / 'solve_stats',
        Path.cwd() / 'solve_stats/activity',
        config.tools_root / 'latex',
    ]
    texinputs = ''
    for p in latex_paths:
        texinputs += str(p) + ';'
    if config.args.verbose >= 2:
        print(f"export TEXINPUTS='{texinputs}'", file=sys.stderr)
    env["TEXINPUTS"] = texinputs
    return env


def build_latex_pdf(builddir, tex_path, language, problem_path=None):
    env = make_environment()

    if shutil.which('latexmk') == None:
        fatal('latexmk not found!')

    latexmk_command = [
        'latexmk',
        '-cd',
        '-g',
        '-pdf',
        '-pdflatex=pdflatex -interaction=nonstopmode -halt-on-error',
    ]
    if config.args.watch:
        latexmk_command.append("-pvc")
    if getattr(config.args, '1'):
        latexmk_command.extend(['-e', '$max_repeat=1'])
    latexmk_command.extend([f'-output-directory={builddir}', tex_path.absolute()])

    ret = util.exec_command(
        latexmk_command,
        expect=0,
        crop=False,
        cwd=builddir,
        stdout=subprocess.PIPE,
        env=env,
        timeout=None,
    )

    if ret.ok is not True:
        error(f'Failure compiling pdf:')
        print(ret.out, file=sys.stderr)
        error(f'return code {ret.ok}')
        error(f'duration {ret.duration}')
        return False

    # rename output filename.pdf to filename.<language>.pdf and symlink it
    built_pdf = rename_with_language((builddir / tex_path.name).with_suffix(".pdf"), language)
    output_pdf = Path(built_pdf.name)
    dest_path = output_pdf if problem_path is None else problem_path / output_pdf
    ensure_symlink(dest_path, builddir / output_pdf, True)

    log(f'PDF written to {dest_path}')
    return True


# 1. Copy the latex/problem.tex file to tmpdir/<problem>/problem.tex,
#    substituting variables.
# 2. Link tmpdir/<problem>/problem_statement to the problem problem_statement directory.
# 3. Link bapc.cls
# 4. Create tmpdir/<problem>/samples.tex.
# 5. Run latexmk and link the resulting problem.xy.pdf into the problem directory.
def build_problem_pdf(problem, language, solution=False):
    """
    Arguments:
    -- language: str, the two-latter language code appearing the file name, such as problem.en.tex
    """
    log(f"Building {('statement' if not solution else 'solution')} PDF for language {language}")
    main_file = 'solution.tex' if solution else 'problem.tex'
    prepare_problem(problem)

    builddir = problem.tmpdir

    local_data = Path(main_file)
    util.copy_and_substitute(
        local_data if local_data.is_file() else config.tools_root / 'latex' / main_file,
        builddir / main_file,
        {
            'problemlabel': problem.label,
            'problemyamlname': problem.settings.name[language].replace('_', ' '),
            'problemauthor': problem.settings.author,
            'timelimit': get_tl(problem),
            'problemdir': problem.path.absolute().as_posix(),
            'builddir': problem.tmpdir.as_posix(),
            'stmlang': language,
        },
    )

    return build_latex_pdf(builddir, builddir / main_file, language, problem.path)


def build_problem_pdfs(problem, solutions=False):
    """Build PDFs for various languages. If list of languages is specified,
    (either via config files or --language arguments), build those. Otherwise
    build all languages for which there is a statement latex source.
    """
    if config.args.languages is not None:
        for lang in config.args.languages:
            if lang not in problem.statement_languages:
                fatal(f"No statement source for language {lang}")
        languages = config.args.languages
    else:
        languages = problem.statement_languages

    return all(build_problem_pdf(problem, lang, solutions) for lang in languages)


def find_logo():
    for directory in ["", "../"]:
        for extension in ["pdf", "png", "jpg"]:
            logo = Path(directory + 'logo.' + extension)
            if logo.exists():
                return logo
    return config.tools_root / 'latex/images/logo-not-found.pdf'


# Build a pdf for an entire problemset in the given language. Explanation in latex/readme.md
def build_contest_pdf(contest, problems, tmpdir, language, solutions=False, web=False):
    log(
        f"Building contest {'statements' if not solutions else 'solutions'} PDF for language {language} "
    )
    builddir = tmpdir / contest
    builddir.mkdir(parents=True, exist_ok=True)
    build_type = 'solution' if solutions else 'problem'

    main_file = 'solutions' if solutions else 'contest'
    main_file += '-web.tex' if web else '.tex'

    default_config_data = {
        'title': 'TITLE',
        'subtitle': '',
        'year': 'YEAR',
        'author': 'AUTHOR',
        'testsession': '',
        'blank_page_text': '',
    }
    config_data = contest_yaml()
    for x in default_config_data:
        if x not in config_data:
            config_data[x] = default_config_data[x]
    config_data['testsession'] = '\\testsession' if config_data.get('testsession') else ''
    config_data['logofile'] = find_logo().as_posix()
    config_data['stmlang'] = language

    local_contest_data = Path('contest_data.tex')
    util.copy_and_substitute(
        local_contest_data
        if local_contest_data.is_file()
        else config.tools_root / 'latex/contest_data.tex',
        builddir / 'contest_data.tex',
        config_data,
    )

    problems_data = ''

    if solutions:
        # include a header slide in the solutions PDF
        headerlangtex = Path(f'solution_header.{language}.tex')
        headertex = Path('solution_header.tex')
        if headerlangtex.exists():
            problems_data += f'\\input{{{headerlangtex}}}\n'
        elif headertex.exists():
            problems_data += f'\\input{{{headertex}}}\n'

    local_per_problem_data = Path(f'contest-{build_type}.tex')
    per_problem_data = (
        local_per_problem_data
        if local_per_problem_data.is_file()
        else config.tools_root / 'latex' / f'contest-{build_type}.tex'
    ).read_text()

    for problem in problems:
        if build_type == 'problem':
            prepare_problem(problem)

        if solutions:
            solutiontex = problem.path / 'problem_statement/solution.tex'
            solutionlangtex = problem.path / f'problem_statement/solution.{language}.tex'
            if solutionlangtex.is_file():
                # All is good
                pass
            elif solutiontex.is_file():
                warn(f'{problem.name}: Rename solution.tex to solution.{language}.tex')
                continue
            else:
                warn(f'{problem.name}: solution.{language}.tex not found')
                continue

        problems_data += util.substitute(
            per_problem_data,
            {
                'problemlabel': problem.label,
                'problemyamlname': problem.settings.name[language].replace('_', ' '),
                'problemauthor': problem.settings.author,
                'timelimit': get_tl(problem),
                'problemdir': problem.path.absolute().as_posix(),
                'problemdirname': problem.name,
                'builddir': problem.tmpdir.as_posix(),
                'stmlang': language,
            },
        )

    if solutions:
        # include a footer slide in the solutions PDF
        footerlangtex = Path(f'solution_footer.{language}.tex')
        footertex = Path('solution_footer.tex')
        if footerlangtex.exists():
            problems_data += f'\\input{{{footerlangtex}}}\n'
        elif footertex.exists():
            problems_data += f'\\input{{{footertex}}}\n'

    (builddir / f'contest-{build_type}s.tex').write_text(problems_data)

    return build_latex_pdf(builddir, Path(main_file), language)


def build_contest_pdfs(contest, problems, tmpdir, solutions=False, web=False):
    """Build contest PDFs for all available languages"""
    statement_languages = set.intersection(*(set(p.statement_languages) for p in problems))
    if not statement_languages:
        fatal("No statement language present in every problem.")
    if config.args.languages is not None:
        languages = config.args.languages
        for lang in set(languages) - statement_languages:
            fatal(f"Unable to build all statements for language {lang}")
    else:
        languages = statement_languages
    return all(
        build_contest_pdf(contest, problems, tmpdir, lang, solutions, web) for lang in languages
    )
