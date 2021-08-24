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


def create_samples_file(problem):
    builddir = problem.tmpdir

    # create the samples.tex file
    # For samples, find all .in/.ans pairs.
    samples = problem.testcases(needans=True, only_sample=True, statement_samples=True)
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
                samples_data += f'\\{mode}{{{interaction_file}}}\n'
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
            samples_data += f'\\Sample{{{sample.in_path}}}{{{sample.ans_path}}}\n'
    samples_file_path.write_text(samples_data)


# Steps needed for both problem and contest compilation.
def prepare_problem(problem):
    builddir = problem.tmpdir
    builddir.mkdir(exist_ok=True)

    create_samples_file(problem)


def get_tl(problem_config):
    tl = problem_config.timelimit
    tl = int(tl) if abs(tl - int(tl)) < 0.0001 else tl

    print_tl = True
    if 'print_timelimit' in problem_config:
        print_tl = problem_config.print_timelimit
    elif hasattr(config.args, 'no_timelimit'):
        print_tl = not config.args.no_timelimit
    else:
        print_tl = True

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
    if getattr(config.args, 'watch', False):
        latexmk_command.append("-pvc")
    if getattr(config.args, '1', False):
        latexmk_command.extend(['-e', '$max_repeat=1'])
    latexmk_command.extend([f'-output-directory={builddir}', tex_path])

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

    util.copy_and_substitute(
        config.tools_root / 'latex' / main_file,
        builddir / main_file,
        {
            'problemlabel': problem.label,
            'problemyamlname': problem.settings.name.replace('_', ' '),
            'problemauthor': problem.settings.author,
            'timelimit': get_tl(problem.settings),
            'problemdir': problem.path.absolute().as_posix(),
            'builddir': problem.tmpdir.as_posix(),
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
# TODO: Extract data from DomJudge API using RGL tools.
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
    config_data = util.read_yaml_settings(Path('contest.yaml'))
    for x in default_config_data:
        if x not in config_data:
            config_data[x] = default_config_data[x]
    config_data['testsession'] = '\\testsession' if config_data.get('testsession') else ''
    config_data['logofile'] = find_logo().as_posix()

    util.copy_and_substitute(
        config.tools_root / 'latex/contest-data.tex', builddir / 'contest_data.tex', config_data
    )

    problems_data = ''

    if solutions:
        # include a header slide in the solutions PDF
        headertex = Path('solution_header.tex')
        if headertex.exists():
            problems_data += f'\\input{{{headertex}}}\n'

    per_problem_data = (config.tools_root / 'latex' / f'contest-{build_type}.tex').read_text()

    for problem in problems:
        if build_type == 'problem':
            prepare_problem(problem)

        problems_data += util.substitute(
            per_problem_data,
            {
                'problemlabel': problem.label,
                'problemyamlname': problem.settings.name.replace('_', ' '),
                'problemauthor': problem.settings.author,
                'timelimit': get_tl(problem.settings),
                'problemdir': problem.path.absolute().as_posix(),
                'builddir': problem.tmpdir.as_posix(),
            },
        )

    if solutions:
        # include a statistics slide in the solutions PDF
        footer_tex = Path('solution_footer.tex')
        if footer_tex.exists():
            problems_data += f'\\input{{{footer_tex}}}\n'

    (builddir / f'contest-{build_type}s.tex').write_text(problems_data)

    return build_latex_pdf(builddir, config.tools_root / 'latex' / main_file)
