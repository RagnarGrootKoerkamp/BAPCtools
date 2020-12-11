# Subcommands for building problem pdfs from the latex source.

import os
import util
import re
import subprocess
import tempfile
from pathlib import Path

import config
import util
from util import *
from colorama import Fore, Style

PDFLATEX = ['pdflatex', '-interaction=nonstopmode', '-halt-on-error']


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
    builddir = problem.tmpdir

    # create the samples.tex file
    samples = problem.testcases(needans=True, only_sample=True)
    samples_file_path = builddir / 'samples.tex'

    if samples is False:
        samples_file_path.write_text('')
        return

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
            samples_data += tex_escape(sample.in_path.read_text())
            samples_data += '&\n'
            samples_data += tex_escape(sample.ans_path.read_text())
            samples_data += '\\\\\n\\end{Sample}\n\n'
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


def get_environment():
    env = os.environ.copy()
    # Search the contest directory and the latex directory.
    inputs = ''
    paths = [
            Path.cwd(),
            Path.cwd() / 'solve_stats',
            Path.cwd() / 'solve_stats/activity',
            config.tools_root / 'latex'
            ]
    texinputs = ''
    for p in paths:
        texinputs += str(p) + ';'
    if config.args.verbose >= 2:
        print(f"export TEXINPUTS='{texinputs}'")
    env["TEXINPUTS"] = texinputs
    return env


# 1. Copy the latex/problem.tex file to tmpdir/<problem>/problem.tex,
# substituting variables.
# 2. Link tmpdir/<problem>/problem_statement to the problem problem_statement directory.
# 3. Link bapc.cls
# 4. Create tmpdir/<problem>/samples.tex.
# 5. Run pdflatex and link the resulting problem.pdf into the problem directory.
def build_problem_pdf(problem, solutions=False):
    t = 'solution' if solutions else 'problem'
    prepare_problem(problem)

    builddir = problem.tmpdir

    util.copy_and_substitute(
        config.tools_root / f'latex/{t}.tex', builddir / f'{t}.tex', {
            'problemlabel': problem.label,
            'problemyamlname': problem.settings.name.replace('_', ' '),
            'problemauthor': problem.settings.author,
            'timelimit': get_tl(problem.settings),
            'problemdir': problem.path.absolute().as_posix(),
            'builddir': problem.tmpdir.as_posix(),
        })

    env = get_environment()
    for i in range(1 if getattr(config.args, '1', False) else 3):
        ret = util.exec_command(
            PDFLATEX + ['-output-directory', builddir,
                        builddir / f'{t}.tex'],
            0,
            False,
            cwd=builddir,
            stdout=subprocess.PIPE,
            env=env,
            timeout=None,
            )
        if ret.ok is not True:
            print(f'{Fore.RED}Failure compiling pdf:{Style.RESET_ALL}\n{ret.out}')
            error(f'return code {ret.ok}')
            error(f'duration {ret.duration}')
            return False

    # link the output pdf
    output_pdf = problem.path / f'{t}.pdf'
    ensure_symlink(output_pdf, builddir / f'{t}.pdf', True)

    print(f'{Fore.GREEN}Pdf written to {output_pdf}{Style.RESET_ALL}')
    return True

def find_logo():
    for directory in ["", "../"]:
        for extension in ["pdf", "png", "jpg"]:
            logo = Path(directory + 'logo.' + extension)
            if logo.exists(): return logo
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
    config_data = util.read_yaml(Path('contest.yaml'))
    for x in default_config_data:
        if x not in config_data: config_data[x] = default_config_data[x]    
    config_data['testsession'] = '\\testsession' if config_data.get('testsession') else ''
    config_data['logofile'] = find_logo().as_posix()

    util.copy_and_substitute(config.tools_root / 'latex/contest-data.tex',
                             builddir / 'contest_data.tex', config_data)

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
            per_problem_data, {
                'problemlabel': problem.label,
                'problemyamlname': problem.settings.name.replace('_', ' '),
                'problemauthor': problem.settings.author,
                'timelimit': get_tl(problem.settings),
                'problemdir': problem.path.absolute().as_posix(),
                'builddir': problem.tmpdir.as_posix(),
            })

    if solutions:
        # include a statistics slide in the solutions PDF
        footer_tex = Path('solution_footer.tex')
        if footer_tex.exists():
            problems_data += f'\\input{{{footer_tex}}}\n'

    (builddir / f'contest-{build_type}s.tex').write_text(problems_data)

    env = get_environment()
    for i in range(1 if getattr(config.args, '1', False) else 3):
        ret = util.exec_command(
            PDFLATEX + ['-output-directory', builddir,
                        config.tools_root / 'latex' / main_file],
            0,
            False,
            cwd=builddir,
            stdout=subprocess.PIPE,
            env=env,
            timeout=None,
            )
        if ret.ok is not True:
            print(f'{Fore.RED}Failure compiling pdf:{Style.RESET_ALL}\n{ret.out}')
            error(f'return code {ret.ok}')
            error(f'duration {ret.duration}')
            return False

    # link the output pdf
    output_pdf = Path(main_file).with_suffix('.pdf')
    ensure_symlink(output_pdf, builddir / output_pdf, True)

    print(f'{Fore.GREEN}Pdf written to {output_pdf}{Style.RESET_ALL}')
    return True
