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
from util import _c

PDFLATEX = ['pdflatex', '-interaction=nonstopmode', '-halt-on-error']


# When output is True, copy the file when args.cp is true.
def ensure_symlink(link, target, output=False):
    if output and hasattr(config.args, 'cp') and config.args.cp == True:
        if link.exists() or link.is_symlink(): link.unlink()
        shutil.copyfile(target, link)
        return

    if link.is_symlink() or link.exists(): link.unlink()
    link.symlink_to(target.resolve())


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
    has_newline = text[-1] is '\n'
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
        samples_data += '\\begin{Sample}\n'
        samples_data += tex_escape(sample.with_suffix('.in').read_text())
        samples_data += '&\n'
        samples_data += tex_escape(sample.with_suffix('.ans').read_text())
        samples_data += '\\\\\n\\end{Sample}\n\n'
    samples_file_path.write_text(samples_data)


# Steps needed for both problem and contest compilation.
def prepare_problem(problem):
    builddir = config.tmpdir / problem
    builddir.mkdir(exist_ok=True)
    ensure_symlink(builddir / 'statement', problem / 'problem_statement')

    create_samples_file(problem)


def get_tl(problem_config):
    tl = problem_config['timelimit']
    tl = int(tl) if abs(tl - int(tl)) < 0.0001 else tl
    
    print_tl = True
    if 'print_timelimit' in problem_config:
        print_tl = problem_config['print_timelimit']
    else:
        print_tl = not config.args.no_timelimit

    return tl if print_tl else ''


# 1. Copy the latex/problem.tex file to tmpdir/<problem>/problem.tex,
# substituting variables.
# 2. Link tmpdir/<problem>/statement to the problem statement directory.
# 3. Link bapc.cls
# 4. Create tmpdir/<problem>/samples.tex.
# 5. Run pdflatex and link the resulting problem.pdf into the problem directory.
def build_problem_pdf(problem):
    prepare_problem(problem)

    builddir = config.tmpdir / problem
    problem_config = util.read_configs(problem)
    problemid = ord(problem_config['probid']) - ord('A')

    util.copy_and_substitute(config.tools_root / 'latex/problem.tex', builddir / 'problem.tex', {
        'problemid': problemid,
        'timelimit': get_tl(problem_config)
    })
    ensure_symlink(builddir / 'bapc.cls', config.tools_root / 'latex/bapc.cls')

    builddir = config.tmpdir / problem
    for i in range(3):
        ok, err, out = util.exec_command(
            PDFLATEX + ['-output-directory', builddir, builddir / 'problem.tex'],
            0, False,
            cwd=builddir,
            stdout=subprocess.PIPE
            )
        if ok is not True:
            print(f'{_c.red}Failure compiling pdf:{_c.reset}\n{out}')
            return False

    # link the output pdf
    output_pdf = problem / 'problem.pdf'
    ensure_symlink(output_pdf, builddir / 'problem.pdf', True)

    print(f'{_c.green}Pdf written to {output_pdf}{_c.reset}')
    return True


def find_logo():
    logo = Path('logo.pdf')
    if logo.exists(): return logo
    logo = Path('../logo.pdf')
    if logo.exists(): return logo
    return config.tools_root / 'latex/images/logo-not-found.pdf'


# Build a pdf for an entire problemset. Explanation in latex/readme.md
def build_contest_pdf(contest, problems, solutions=False, web=False):
    builddir = config.tmpdir / contest
    builddir.mkdir(parents=True, exist_ok=True)
    build_type = 'solution' if solutions else 'problem'

    # TODO: fix solutions
    # TODO: Extract data from DomJudge API using RGL tools.
    #statement = not solutions

    main_file = 'solutions.tex' if solutions else ('contest-web.tex' if web else 'contest.tex')
    ensure_symlink(builddir / 'bapc.cls', config.tools_root / 'latex/bapc.cls')
    ensure_symlink(builddir / 'images', config.tools_root / 'latex/images')
    ensure_symlink(builddir / main_file, config.tools_root / 'latex' / main_file)
    config_data = util.read_yaml(Path('contest.yaml'))
    config_data['testsession'] = '\\testsession' if config_data['testsession'] else ''
    print(config_data)
    util.copy_and_substitute(config.tools_root / 'latex/contest-data.tex',
            builddir / 'contest_data.tex', config_data)
    statstex = Path('solution_stats.tex')
    if statstex.exists():
        ensure_symlink(builddir / 'solutions_stats.tex', Path('solution_stats.tex'))
    ensure_symlink(builddir / 'logo.pdf', find_logo())

    problems_data = ''
    per_problem_data = (config.tools_root / 'latex' / f'contest-{build_type}.tex').read_text()

    # Some logic to prevent duplicate problem IDs.
    seen = set()
    next_spare = 0
    for problem, _, problem_config in util.sort_problems(problems):
        prepare_problem(problem)
        problemid = ord(problem_config['probid']) - ord('A')
        id_ok = True
        while problemid in seen:
            problemid = next_spare
            next_spare += 1
            id_ok = False
        if not id_ok:
            print(
                f"{_c.red}Problem {problem} has id {problem_config['probid']} which was already used before. Using {chr(ord('A')+problemid)} instead.{_c.reset}"
            )
        seen.add(problemid)

        problems_data += util.substitute(per_problem_data, {
            'problemid': problemid,
            'timelimit': get_tl(problem_config),
            'problemdir': config.tmpdir / problem,
        })

    # include a statistics slide in the solutions PDF
    if solutions and statstex.exists():
        problems_data += f'\\input{{{statstex}}}\n'

    (builddir / f'contest-{build_type}s.tex').write_text(problems_data)

    for i in range(3):
        ok, err, out = util.exec_command(
            PDFLATEX + ['-output-directory', builddir, (builddir / main_file).with_suffix('.tex')],
            0, False,
            cwd=builddir,
            stdout=subprocess.PIPE
            )
        if ok is not True:
            print(f'{_c.red}Failure compiling pdf:{_c.reset}\n{out}')
            return False

    # link the output pdf
    output_pdf = Path(main_file).with_suffix('.pdf')
    ensure_symlink(output_pdf, builddir / output_pdf, True)

    print(f'{_c.green}Pdf written to {output_pdf}{_c.reset}')
    return True
