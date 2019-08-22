# Subcommands for building problem pdfs from the latex source.

import os
import util
import re
import subprocess
import tempfile
from pathlib import Path

import config
import util
from util import _c

PDFLATEX = ['pdflatex', '-halt-on-error']


def ensure_symlink(link, target):
    if link.exists() or link.is_symlink(): return
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


# 1. Copy the latex/problem.tex file to tmpdir/<problem>/problem.tex,
# substituting variables.
# 2. Link tmpdir/<problem>/statement to the problem statement directory.
# 3. Link bapc.cls
# 4. Create tmpdir/<problem>/samples.tex.
# 5. Run pdflatex and link the resulting problem.pdf into the problem directory.
def build_problem_pdf(problem):
    builddir = config.tmpdir / problem
    builddir.mkdir(exist_ok=True)
    problem_config = util.read_configs(problem)
    problemid = ord(problem_config['probid']) - ord('A')
    tl = problem_config['timelimit']
    tl = int(tl) if abs(tl - int(tl)) < 0.01 else tl

    util.copy_and_substitute(config.tools_root / 'latex/problem.tex', builddir / 'problem.tex', {
        'problemid': problemid,
        'timelimit': tl,
    })
    ensure_symlink(builddir / 'statement', problem / 'problem_statement')
    ensure_symlink(builddir / 'bapc.cls', config.tools_root / 'latex/bapc.cls')

    create_samples_file(problem)

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
    if output_pdf.exists() or output_pdf.is_symlink(): output_pdf.unlink()
    output_pdf.symlink_to(builddir / 'problem.pdf')

    print(f'{_c.green}Pdf written to {output_pdf}{_c.reset}')
    return True


def find_logo():
    logo = Path('../logo.pdf')
    if logo.exists():
        return logo
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
    ensure_symlink(builddir / 'contest_data.tex', Path('contest.tex'))
    statstex = Path('solution_stats.tex')
    if statstex.exists():
        ensure_symlink(builddir / 'solutions_stats.tex', Path('solution_stats.tex'))
    ensure_symlink(builddir / 'logo.pdf', find_logo())

    problems_data = ''
    per_problem_data = (config.tools_root / 'latex' / f'contest-{build_type}.tex').read_text()

    # Some logic to prevent duplicate problem IDs.
    seen = set()
    next_spare = 25
    for problem, _, problem_config in util.sort_problems(problems):
        problemid = ord(problem_config['probid']) - ord('A')
        if problemid in seen:
            problemid = next_spare
            next_spare -= 1
            print(
                f"{_c.red}Problem {problem} has id {problem_config['probid']} which was already used before. Using {chr(ord('A')+problemid)} instead.{_c.reset}"
            )
        seen.add(problemid)

        tl = problem_config['timelimit']
        tl = int(tl) if abs(tl - int(tl)) < 0.01 else tl
        problems_data += util.substitute(per_problem_data, {
            'problemid': problemid,
            'timelimit': tl,
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
    ensure_symlink(output_pdf, builddir / output_pdf)

    print(f'{_c.green}Pdf written to {output_pdf}{_c.reset}')
    return True
