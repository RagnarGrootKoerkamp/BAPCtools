#!/usr/bin/python3

import sys
import argparse
import os
import os.path
import re
import zipfile
import config
from util import _c
from pathlib import Path


def build_problem_zip(problem, output, settings):
    """Make DOMjudge ZIP file for specified problem."""
    # Glob, required?
    files = [
        ('domjudge-problem.ini', True),
        ('problem.yaml', True),
        ('problem.pdf', True),
        ('problem_statement/*', True),
        ('data/sample/*.in', True),
        ('data/sample/*.ans', True),
        ('data/secret/*.in', True),
        ('data/secret/*.ans', True),
        ('submissions/accepted/**/*', True),
        ('submissions/wrong_answer/**/*', False),
        ('submissions/time_limit_exceeded/**/*', False),
        ('submissions/run_time_error/**/*', False),
    ]

    if settings.validation == 'custom':
        files.append(('output_validators/**/*', True))

    if config.args.kattis:
        files.append(('input_validators/**/*', True))

    print("Preparing to make ZIP file for problem dir %s" % problem)

    # Build list of files to store in ZIP file.
    copyfiles = []

    for pattern, required in files:
        paths = list(Path(problem).glob(pattern))
        if required and len(paths) == 0:
            print(f'{_c.red}No matches for required path {pattern}{_c.reset}.')
        for f in paths:
            copyfiles.append((f, f.relative_to(Path(problem))))


    # Build .ZIP file.
    print("writing ZIP file:", output)

    zf = zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    # For kattis, write to problemname/<file> instead of just <file>.
    root = ''
    if config.args.kattis:
        root = os.path.basename(os.path.normpath(problem))
        root = re.sub(r'[^a-z0-9]', '', root.lower())
    for fname in copyfiles:
        source = fname
        target = fname
        if isinstance(fname, tuple):
            source = fname[0]
            target = fname[1]
        zf.write(
            source, target,
            compress_type=zipfile.ZIP_DEFLATED)

    # Done.
    zf.close()
    print("done")
    print()

    return True


# Assumes the current working directory has: the zipfiles and
# contest.pdf
# contest-web.pdf
# solutions.pdf
# Output is <outfile>
def build_contest_zip(zipfiles, outfile, args):
    print("writing ZIP file %s" % outfile)

    zf = zipfile.ZipFile(outfile, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    for fname in zipfiles:
        zf.write(fname, fname, compress_type=zipfile.ZIP_DEFLATED)

    if not args.kattis:
        for fname in ['contest.pdf', 'contest-web.pdf', 'solutions.pdf', 'solutions-web.pdf']:
            if Path(fname).is_file():
                zf.write(fname, fname, compress_type=zipfile.ZIP_DEFLATED)

    print("done")
    print()

    zf.close()


# preparing a kattis directory involves creating lots of symlinks to files which
# are the same. If it gets changed for the format, we copy the file and modify
# it accordingly.
def prepare_kattis_directory():
    p = Path('kattis')
    p.mkdir(parents=True, exist_ok=True)


def prepare_kattis_problem(problem, settings):
    shortname = alpha_num(os.path.basename(os.path.normpath(problem)))
    path = os.path.join('kattis', shortname)
    orig_path = os.path.join('../../', problem)

    if not os.path.exists(path):
        os.mkdir(path)

    for same in ['data', 'generators', 'problem.yaml', 'submissions']:
        symlink_quiet(os.path.join(orig_path, same), os.path.join(path, same))

    # make an input validator
    vinput = os.path.join(path, 'input_format_validators')
    if not os.path.exists(vinput):
        os.mkdir(vinput)

    symlink_quiet(
        os.path.join('../', orig_path, 'input_validators'),
        os.path.join(vinput, shortname + '_validator'))

    # After this we only look inside directories.
    orig_path = os.path.join('../', orig_path)

    # make a output_validators directory with in it "$shortname-validator"
    if settings.validation == 'custom':
        voutput = os.path.join(path, 'output_validators')
        if not os.path.exists(voutput):
            os.mkdir(voutput)
        symlink_quiet(
            os.path.join(orig_path, 'output_validators'),
            os.path.join(voutput, shortname + '_validator'))

    # make a problem statement with problem.en.tex -> problem.en.tex,
    # but all other files intact.
    pst = 'problem_statement'
    st = os.path.join(path, pst)
    if not os.path.exists(st):
        os.mkdir(st)

    # determine the files in the 'problem statement' directory
    wd = os.getcwd()
    os.chdir(os.path.join(problem, pst))
    files = glob('*')
    os.chdir(wd)

    assert "problem.en.tex" in files

    # remember: current wd is st
    for f in files:
        if f != "problem.en.tex":
            symlink_quiet(os.path.join(orig_path, pst, f), os.path.join(st, f))

    source = os.path.join(problem, pst, 'problem.en.tex')
    target = os.path.join(st, 'problem.en.tex')
    if os.path.islink(target) or os.path.exists(target):
        os.unlink(target)
    with open(source, 'r') as f, open(target, 'w') as g:
        for line in f:
            if line == "\\begin{Input}\n":
                g.write("\section*{Input}\n")
            elif line == "\\begin{Output}\n":
                g.write("\section*{Output}\n")
            elif line in ["\\end{Input}\n", "\\end{Output}\n"]:
                g.write("\n")
            else:
                g.write(line)


def build_sample_zip(problems):
    zf = zipfile.ZipFile(
        'samples.zip', mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    for problem in util.sort_problems(problems):
        letter = problem[1]
        problem = problem[0]
        samples = util.get_testcases(problem, needans=True, only_sample=True)
        for i in range(0, len(samples)):
            sample = samples[i]
            zf.write(sample + '.in', os.path.join(letter, str(i)) + '.in')
            zf.write(sample + '.ans', os.path.join(letter, str(i)) + '.ans')

    zf.close()
    print("Wrote zip to samples.zip")
