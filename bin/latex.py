# Subcommands for building problem pdfs from the latex source.

import os
import util
import re
import subprocess
import tempfile
import shutil
from pathlib import Path

import config
import util
from util import cc, ensure_symlink

PDFLATEX = ['pdflatex', '-interaction=nonstopmode', '-halt-on-error']


def require_latex_build_dir():
    # Set up the build directory if it does not yet exist.
    builddir = config.tools_root / 'latex/build'
    if not builddir.is_dir():
        if builddir.is_symlink():
            builddir.unlink()
        tmpdir = Path(tempfile.mkdtemp(prefix='bapctools_latex_'))
        builddir.symlink_to(tmpdir)
    return builddir


# https://stackoverflow.com/questions/16259923/how-can-i-escape-latex-special-characters-inside-django-templates
def tex_escape(text):
    """
        :param text: a plain text message
        :return: the message escaped to appear correctly in LaTeX
    """
    conv = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        #        '_': r'\_',
        # For monospaced purpose, use instead:
        '_': r'\char`_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\^{}',
        #        '\\': r'\textbackslash{}',
        # For monospaced purpose, use instead:
        '\\': r'\char`\\',
        '<': r'\textless{}',
        '>': r'\textgreater{}',
        '\'': r'\textquotesingle{}',
        '\n': '\\newline\n',
    }
    regex = re.compile(
        '|'.join(re.escape(str(key)) for key in sorted(conv.keys(), key=lambda item: -len(item))),
        re.MULTILINE)

    # Remove the trailing newline because it will be replaced by \\newline\n
    has_newline = len(text) > 0 and text[-1] == '\n'
    if has_newline: text = text[:-1]
    text = regex.sub(lambda match: conv[match.group()], text)
    # Escape leading spaces separately
    regex = re.compile('^ ')
    text = regex.sub('\\\\phantom{.}', text)
    if has_newline: text += '\n'
    return text


def create_samples_file(problem):
    builddir = config.tmpdir / problem

    # create the samples.tex file
    samples = util.get_testcases(problem, needans=True, only_sample=True)
    samples_file_path = builddir / 'samples.tex'
    samples_data = ''

    for sample in samples:
        interaction_file = sample.with_suffix('.interaction')
        if interaction_file.is_file():
            samples_data += '\\InteractiveSampleHeading\n'
            lines = interaction_file.read_text()
            last = 'x'
            cur = ''

            def flush():
                assert last in '<>'
                nonlocal samples_data
                mode = 'InteractiveRead' if last == '<' else 'InteractiveWrite'
                samples_data += '\\begin{' + mode + '}\n'
                samples_data += tex_escape(cur)
                samples_data += '\\end{' + mode + '}\n\n'

            for line in lines.splitlines():
                if line[0] == last:
                    cur += line[1:] + '\n'
                else:
                    if cur: flush()
                    cur = line[1:] + '\n'
                    last = line[0]
            flush()
        else:
            samples_data += '\\begin{Sample}\n'
            samples_data += tex_escape(sample.with_suffix('.in').read_text())
            samples_data += '&\n'
            samples_data += tex_escape(sample.with_suffix('.ans').read_text())
            samples_data += '\\\\\n\\end{Sample}\n\n'
    samples_file_path.write_text(samples_data)


# Steps needed for both problem and contest compilation.
def prepare_problem(problem):
    builddir = config.tmpdir / problem.id
    builddir.mkdir(exist_ok=True)
    ensure_symlink(builddir / 'problem_statement', problem.path / 'problem_statement')

    create_samples_file(problem.path)


def get_tl(problem_config):
    tl = problem_config['timelimit']
    tl = int(tl) if abs(tl - int(tl)) < 0.0001 else tl

    print_tl = True
    if 'print_timelimit' in problem_config:
        print_tl = problem_config['print_timelimit']
    elif hasattr(config.args, 'no_timelimit'):
        print_tl = not config.args.no_timelimit
    else:
        print_tl = True

    return tl if print_tl else ''


# 1. Copy the latex/problem.tex file to tmpdir/<problem>/problem.tex,
# substituting variables.
# 2. Link tmpdir/<problem>/problem_statement to the problem problem_statement directory.
# 3. Link bapc.cls
# 4. Create tmpdir/<problem>/samples.tex.
# 5. Run pdflatex and link the resulting problem.pdf into the problem directory.
def build_problem_pdf(problem):
    prepare_problem(problem)

    builddir = config.tmpdir / problem.id

    util.copy_and_substitute(
        config.tools_root / 'latex/problem.tex', builddir / 'problem.tex', {
            'problemlabel': problem.label,
            'problemyamlname': problem.config['name'],
            'problemauthor': problem.config.get('author'),
            'timelimit': get_tl(problem.config),
            'problemdir': builddir,
        })

    ensure_symlink(builddir / 'bapc.cls', config.tools_root / 'latex/bapc.cls')

    for i in range(3):
        ok, err, out = util.exec_command(
            PDFLATEX + ['-output-directory', builddir, builddir / 'problem.tex'],
            0,
            False,
            cwd=builddir,
            stdout=subprocess.PIPE)
        if ok is not True:
            print(f'{cc.red}Failure compiling pdf:{cc.reset}\n{out}')
            return False

    # link the output pdf
    output_pdf = problem.path / 'problem.pdf'
    ensure_symlink(output_pdf, builddir / 'problem.pdf', True)

    print(f'{cc.green}Pdf written to {output_pdf}{cc.reset}')
    return True


def find_logo():
    for directory in ["", "../"]:
        for extension in ["pdf", "png", "jpg"]:
            logo = Path(directory + 'logo.' + extension)
            if logo.exists(): return logo
    return config.tools_root / 'latex/images/logo-not-found.pdf'


# Build a pdf for an entire problemset. Explanation in latex/readme.md
# Specify `order` to order the problems by e.g. difficulty.
# TODO: Extract data from DomJudge API using RGL tools.
def build_contest_pdf(contest, problems, solutions=False, web=False):
    builddir = config.tmpdir / contest
    builddir.mkdir(parents=True, exist_ok=True)
    build_type = 'solution' if solutions else 'problem'

    main_file = 'solutions' if solutions else 'contest'
    main_file += '-web.tex' if web else '.tex'

    if solutions:
        ensure_symlink(builddir / 'solutions-base.tex',
                       config.tools_root / 'latex/solutions-base.tex')
    ensure_symlink(builddir / 'bapc.cls', config.tools_root / 'latex/bapc.cls')
    ensure_symlink(builddir / 'images', config.tools_root / 'latex/images')
    ensure_symlink(builddir / main_file, config.tools_root / 'latex' / main_file)

    config_data = util.read_yaml(Path('contest.yaml'))
    config_data['testsession'] = '\\testsession' if config_data.get('testsession') else ''

    util.copy_and_substitute(config.tools_root / 'latex/contest-data.tex',
                             builddir / 'contest_data.tex', config_data)

    ensure_symlink(builddir / 'logo.pdf', find_logo())

    problems_data = ''

    # Link the solve stats directory if it exists.
    solve_stats = Path('solve_stats')
    if solve_stats.exists():
        ensure_symlink(builddir / 'solve_stats', solve_stats)

    # include a header slide in the solutions PDF
    headertex = Path('solution_header.tex')
    if headertex.exists(): ensure_symlink(builddir / 'solution_header.tex', headertex)
    if solutions and headertex.exists(): problems_data += f'\\input{{{headertex}}}\n'

    per_problem_data = (config.tools_root / 'latex' / f'contest-{build_type}.tex').read_text()

    # Some logic to prevent duplicate problem IDs.
    for problem in problems:
        prepare_problem(problem)
        id_ok = True

        problems_data += util.substitute(
            per_problem_data, {
                'problemlabel': problem.label,
                'problemyamlname': problem.config['name'],
                'problemauthor': problem.config.get('author'),
                'timelimit': get_tl(problem.config),
                'problemdir': config.tmpdir / problem.id,
            })

    # include a statistics slide in the solutions PDF
    footer_tex = Path('solution_footer.tex')
    if footer_tex.exists(): ensure_symlink(builddir / 'solution_footer.tex', footer_tex)
    if solutions and footer_tex.exists(): problems_data += f'\\input{{{footer_tex}}}\n'

    (builddir / f'contest-{build_type}s.tex').write_text(problems_data)

    for i in range(3):
        ok, err, out = util.exec_command(
            PDFLATEX + ['-output-directory', builddir, (builddir / main_file).with_suffix('.tex')],
            0,
            False,
            cwd=builddir,
            stdout=subprocess.PIPE)
        if ok is not True:
            print(f'{cc.red}Failure compiling pdf:{cc.reset}\n{out}')
            return False

    # link the output pdf
    output_pdf = Path(main_file).with_suffix('.pdf')
    ensure_symlink(output_pdf, builddir / output_pdf, True)

    print(f'{cc.green}Pdf written to {output_pdf}{cc.reset}')
    return True
