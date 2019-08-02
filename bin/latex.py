# Subcommands for building problem pdfs from the latex source.

import os
import util
import re
import subprocess
from pathlib import Path

import config

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
  }
  regex = re.compile('|'.join(
      re.escape(str(key))
      for key in sorted(conv.keys(), key=lambda item: -len(item))))
  text = regex.sub(lambda match: conv[match.group()], text)
  # Escape leading spaces separately
  regex = re.compile('^ ')
  text = regex.sub('\\\\phantom{.}', text)
  return text


# Build a pdf for the problem. Explanation in latex/readme.md
def build_problem_pdf(problem, make_pdf=True):
  builddir = require_latex_build_dir()

  # Make the build/<problem> directory
  (builddir/problem).mkdir(parents=True, exist_ok=True)
  problemdir = builddir/ 'problem'
  # build/problem -> build/<problem>
  if problemdir.exists():
      problemdir.unlink()

  problemdir.symlink_to(problem)

  # link problem_statement dir
  statement_target = builddir / 'problem/problem_statement'
  if not statement_target.exists():
    if statement_target.is_symlink():
      statement_target.unlink()
    statement_target.symlink_to((problem/ 'problem_statement').resolve())

  # create the problemid.tex file which sets the section counter
  problemid_file_path = builddir/ 'problem/problemid.tex'
  with open(problemid_file_path, 'wt') as problemid_file:
    problem_config = util.read_configs(problem)
    problemid = ord(problem_config['probid']) - ord('A')
    problemid_file.write('\\setcounter{section}{' + str(problemid) + '}\n')
    # Also renew the timelimit command. Use an integral timelimit if
    # possible
    tl = problem_config['timelimit']
    tl = int(tl) if abs(tl - int(tl)) < 0.25 else tl
    renewcom = '\\renewcommand{\\timelimit}{' + str(tl) + '}\n'
    problemid_file.write(renewcom)

  # create the samples.tex file
  samples = util.get_testcases(problem, needans=True, only_sample=True)
  samples_file_path = builddir/ 'problem/samples.tex'
  with samples_file_path.open('wt') as samples_file:
    for sample in samples:
      samples_file.write('\\begin{Sample}\n')

      with sample.with_suffix('.in').open('rt') as in_file:
        lines = []
        for line in in_file:
          lines.append(tex_escape(line))
        samples_file.write('\\newline\n'.join(lines))

      # Separate the left and the right column.
      samples_file.write('&\n')

      with sample.with_suffix('.ans').open('rt') as ans_file:
        lines = []
        for line in ans_file:
          lines.append(tex_escape(line))
        samples_file.write('\\newline\n'.join(lines))

      # We must include a \\ in latex at the end of the table row.
      samples_file.write('\\\\\n\\end{Sample}\n')

  if not make_pdf:
    return True

  # run pdflatex
  pwd = Path.cwd()
  os.chdir(config.tools_root / 'latex')
  subprocess.call(
      ['pdflatex', '-output-directory', './build/problem', 'problem.tex'])
  os.chdir(pwd)

  # link the output pdf
  pdf_path = problem/ 'problem.pdf'
  if not pdf_path.exists():
    pdf_path.symlink_to(builddir/pdf_path)

  return True


# Build a pdf for an entire problemset. Explanation in latex/readme.md
def build_contest_pdf(contest, problems, solutions=False, web=False):
  builddir = require_latex_build_dir()

  statement = not solutions

  # Make the build/<contest> directory
  (builddir/contest).mkdir(parents=True, exist_ok=True)

  contest_dir = builddir/ 'contest'
  # build/contest -> build/<contest>
  if contest_dir.exists():
    contest_dir.unlink()
  contest_dir.symlink_to(contest)

  # link contest.tex
  config_target = builddir/ 'contest/contest.tex'
  if not config_target.exists():
    if config_target.is_symlink():
      config_target.unlink()
    config_target.symlink_to(Path('contest.tex').resolve())

  # link solution_stats
  stats = Path('solution_stats.tex').resolve()
  if solutions and stats.exists():
    stats_target = builddir/ 'contest/solution_stats.tex'
    if not stats_target.exists():
      if stats_target.is_symlink():
        stats_target.unlink()
      stats_target.symlink_to(stats)

  # Create the contest/problems.tex file.
  t = 'solution' if solutions else 'problem'
  problems_path = builddir/ 'contest'/ (t + 's.tex')
  problems_with_ids = util.sort_problems(problems)
  with open(problems_path, 'wt') as problems_file:
    for problem_with_id in problems_with_ids:
      problem = problem_with_id[0]
      includedir = Path('.')/ 'build'/ problem/ 'problem_statement'
      includepath = includedir / (t+'.tex')
      if (config.tools_root/ 'latex'/ includepath).exists():
        problems_file.write('\\begingroup\\graphicspath{{' +
                            str(includedir) + os.sep +
                            '}}\n')
        problems_file.write('\\input{' + str(Path('.')/'build'/problem/ 'problemid.tex') + '}\n')
        problems_file.write('\\input{' + str(includepath) + '}\n')
        if statement:
          problems_file.write('\\input{' + str(Path('.')/ 'build'/ problem/
            'samples.tex') + '}\n')
        problems_file.write('\\endgroup\n')

    # include a statistics slide in the solutions PDF
    if solutions and stats.exists():
        problems_file.write('\\input{' + str(Path('.')/ 'build'/ 'contest'/ 'solution_stats.tex') + '}\n')

  # Link logo. Either `contest/../logo.png` or `images/logo-not-found.png`
  logo_path = builddir/ 'contest/logo.pdf'
  if not logo_path.exists():
    logo_source = Path('../logo.pdf')
    if logo_source.exists():
      logo_path.symlink_to(logo_source)
    else:
      logo_path.symlink_to( (config.tools_root/ 'latex/images/logo-not-found.pdf').resolve())

  # Run pdflatex for problems
  pwd = os.getcwd()
  os.chdir(config.tools_root/ 'latex')
  f = 'solutions' if solutions else ('contest-web' if web else 'contest')
  # The absolute path is needed, because otherwise the `contest.tex` file
  # in the output directory will get priority.
  if subprocess.call([
      'pdflatex', '-output-directory', './build/contest',
      Path(f+'.tex').resolve()
  ]) != 0:
    os.chdir(pwd)
    # Non-zero exit code marks a failure.
    print(_c.red, 'An error occurred while compiling latex!', _c.reset)
    return False
  os.chdir(pwd)

  # link the output pdf
  output_pdf = Path(f).with_suffix('.pdf')
  if not output_pdf.exists():
    output_pdf.symlink_to(builddir/ contest/ output_pdf)

  return True

# vim: et ts=2 sts=2 sw=2:
