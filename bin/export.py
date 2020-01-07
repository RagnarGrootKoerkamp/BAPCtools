#!/usr/bin/python3

import sys
import argparse
import os
import os.path
import re
import zipfile
import config
import util
from util import _c
from pathlib import Path


def build_samples_zip(problems):
    zf = zipfile.ZipFile('samples.zip',
                         mode="w",
                         compression=zipfile.ZIP_DEFLATED,
                         allowZip64=False)

    for problem in problems:
        samples = util.get_testcases(problem.path, needans=True, only_sample=True)
        sampledir = Path(problem.label)
        for i in range(0, len(samples)):
            sample = samples[i]
            basename = sampledir / str(i + 1)
            zf.write(sample.with_suffix('.in'), basename.with_suffix('.in'))
            zf.write(sample.with_suffix('.ans'), basename.with_suffix('.ans'))

    zf.close()
    print("Wrote zip to samples.zip")


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
        paths = list(util.glob(Path(problem), pattern))
        if required and len(paths) == 0:
            print(f'{_c.red}No matches for required path {pattern}{_c.reset}.')
        for f in paths:
            # TODO: Fix this hack. Maybe just rename input_validators ->
            # input_format_validators everywhere?
            out = Path(str(f).replace('input_validators', 'input_format_validators'))
            copyfiles.append((f, out.relative_to(Path(problem))))

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
        zf.write(source, target, compress_type=zipfile.ZIP_DEFLATED)

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
def build_contest_zip(problems, zipfiles, outfile, args):
    print("writing ZIP file %s" % outfile)

    zf = zipfile.ZipFile(outfile, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    for fname in zipfiles:
        zf.write(fname, fname, compress_type=zipfile.ZIP_DEFLATED)

    # For general zip export, also create pdfs and a samples zip.
    if not args.kattis:
        build_samples_zip(problems)

        for fname in [
                'contest.pdf', 'contest-web.pdf', 'solutions.pdf', 'solutions-web.pdf',
                'samples.zip'
        ]:
            if Path(fname).is_file():
                zf.write(fname, fname, compress_type=zipfile.ZIP_DEFLATED)

    print("done")
    print()

    zf.close()
