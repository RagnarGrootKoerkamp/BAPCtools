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
    samples = problem.testcases(needans=not problem.interactive, needinteraction=problem.interactive, only_sample=True, statement_samples=True, copy=True)
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


def build_latex_pdf(builddir, tex_path, problem_path=None):
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

    # link the output pdf
    output_pdf = Path(tex_path.name).with_suffix('.pdf')
    dest_path = output_pdf if problem_path is None else problem_path / output_pdf
    ensure_symlink(dest_path, builddir / output_pdf, True)

    log(f'Pdf written to {dest_path}')
    return True


# 1. Copy the latex/problem.tex file to tmpdir/<problem>/problem.tex,
# substituting variables.
# 2. Link tmpdir/<problem>/problem_statement to the problem problem_statement directory.
# 3. Link bapc.cls
# 4. Create tmpdir/<problem>/samples.tex.
# 5. Run latexmk and link the resulting problem.pdf into the problem directory.
def build_problem_pdf(problem, solutions=False):
    main_file = 'solution.tex' if solutions else 'problem.tex'
    prepare_problem(problem)

    builddir = problem.tmpdir

    local_data = Path(main_file)
    util.copy_and_substitute(
        local_data if local_data.is_file() else config.tools_root / 'latex' / main_file,
        builddir / main_file,
        {
            'problemlabel': problem.label,
            'problemyamlname': problem.settings.name[problem.language].replace('_', ' '),
            'problemauthor': problem.settings.author,
            'timelimit': get_tl(problem),
            'problemdir': problem.path.absolute().as_posix(),
            'builddir': problem.tmpdir.as_posix(),
            'stmlang': problem.language
        },
    )

    return build_latex_pdf(builddir, builddir / main_file, problem.path)


def find_logo():
    for directory in ["", "../"]:
        for extension in ["pdf", "png", "jpg"]:
            logo = Path(directory + 'logo.' + extension)
            if logo.exists():
                return logo
    return config.tools_root / 'latex/images/logo-not-found.pdf'


# Build a pdf for an entire problemset. Explanation in latex/readme.md
def build_contest_pdf(contest, problems, tmpdir, solutions=False, web=False):
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

    local_contest_data = Path('contest-data.tex')
    util.copy_and_substitute(
        local_contest_data
        if local_contest_data.is_file()
        else config.tools_root / 'latex/contest-data.tex',
        builddir / 'contest_data.tex',
        config_data,
    )

    problems_data = ''

    if solutions:
        # include a header slide in the solutions PDF
        headertex = Path('solution_header.tex')
        if headertex.exists():
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
            if not (problem.path / 'problem_statement/solution.tex').is_file():
                warn(f'solution.tex not found for problem {problem.name}')
                continue

        problems_data += util.substitute(
            per_problem_data,
            {
                'problemlabel': problem.label,
                'problemyamlname': problem.settings.name.replace('_', ' '),
                'problemauthor': problem.settings.author,
                'timelimit': get_tl(problem),
                'problemdir': problem.path.absolute().as_posix(),
                'problemdirname': problem.name,
                'builddir': problem.tmpdir.as_posix(),
            },
        )

    if solutions:
        # include a statistics slide in the solutions PDF
        footer_tex = Path('solution_footer.tex')
        if footer_tex.exists():
            problems_data += f'\\input{{{footer_tex}}}\n'

    (builddir / f'contest-{build_type}s.tex').write_text(problems_data)

    return build_latex_pdf(builddir, Path(main_file))
