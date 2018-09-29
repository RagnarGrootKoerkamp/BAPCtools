#!/usr/bin/python3

import sys
import argparse
import os
import os.path
import re
import zipfile


def build_problem_zip(probdir, output, args):
    """Make DOMjudge ZIP file for specified problem."""

    print("Preparing to make ZIP file for problem dir %s" % probdir)

    # Build list of files to store in ZIP file.
    copyfiles = [ ]

    custom_validator = False

    # Find problem dir.
    try:
        os.listdir(probdir)
    except OSError as e:
        print("ERROR: Can not find problem directory", file=sys.stderr)
        print(e, file=sys.stderr)
        return False

    # Check existence of domjudge-problem.ini and problem.yaml.
    if os.path.isfile(os.path.join(probdir, 'domjudge-problem.ini')):
        copyfiles.append('domjudge-problem.ini')
    else:
        print("ERROR: Can not find domjudge-problem.ini file",
              file=sys.stderr)
        return False

    if os.path.isfile(os.path.join(probdir, 'problem.yaml')):
        copyfiles.append('problem.yaml')

        # Scan problem.yaml file to decide if a custom validator is used.
        with open(os.path.join(probdir, 'problem.yaml')) as f:
            for s in f:
                if 'validation' in s and 'custom' in s and 'default' not in s:
                    custom_validator = True
    else:
        print("WARNING: Can not find problem.yaml file",
              file=sys.stderr)

    if os.path.isfile(os.path.join(probdir, 'problem.pdf')):
        copyfiles.append('problem.pdf')
    else:
        print("WARNING: Can not find problem.pdf file",
              file=sys.stderr)

    if os.path.isfile(os.path.join(probdir, 'problem_statement/problem.tex')):
        copyfiles.append('problem_statement/problem.tex')
    else:
        print("WARNING: Can not find problem.tex file", file=sys.stderr)


    for f in os.listdir(os.path.join(probdir, 'problem_statement')):
        if os.path.splitext(f)[1] in ['.jpg', '.svg', '.png', '.pdf']:
            copyfiles.append('problem_statement/'+f)

    # Find input/output files.
    for (prefix, typ) in (('data/sample', 'sample'),
                          ('data/secret', 'secret')):

        try:
            inoutfiles = os.listdir(os.path.join(probdir, prefix))
        except OSError as e:
            print("ERROR: Can not find %s input/output files" % typ,
                  file=sys.stderr)
            print(e, file=sys.stderr)
            return False

        # Check pairs of input/output files.
        inoutfiles.sort()
        testcases = list(set([ os.path.splitext(fname)[0]
                               for fname in inoutfiles ]))

        # Check pair of .in and .ans exists for every testcase.
        for tc in testcases:
            if '.' in tc:
                print("ERROR: Bad testcase name %s/%s" % (prefix, tc),
                      file=sys.stderr)
                return False
            if not os.path.isfile(os.path.join(probdir, prefix, tc + '.in')):
                print("ERROR: Missing file %s/%s" % (prefix, tc + '.in'),
                      file=sys.stderr)
                return False
            if not os.path.isfile(os.path.join(probdir, prefix, tc + '.ans')):
                print("ERROR: Missing file %s/%s" % (prefix, tc + '.ans'),
                      file=sys.stderr)
                return False

        print("found %d %s test cases" % (len(testcases), typ))

        if len(testcases) == 0:
            print("ERROR: No %s input/output files found" % typ,
                  file=sys.stderr)
            return False

        # Add input/output files to list of files to copy to ZIP.
        for fname in inoutfiles:
            copyfiles.append(os.path.join(prefix, fname))

    # Find solutions.
    submit_types = [
            'accepted', 'wrong_answer', 'time_limit_exceeded', 'run_time_error'
            ]
    try:
        for d in os.listdir(os.path.join(probdir, 'submissions')):
            if d not in submit_types:
                print("ERROR: Found unexpected entry submissions/%s" % d,
                      file=sys.stderr)
                return False
    except OSError as e:
        pass

    nsubmit = 0
    naccept = 0
    for d in submit_types:
        subs = []
        try:
            subs = os.listdir(os.path.join(probdir, 'submissions', d))
        except OSError as e:
            pass
        for fname in subs:
            if not os.path.isfile(os.path.join(probdir,
                                               'submissions', d, fname)):
                print("ERROR: Unexpected non-file submissions/%s/%s" %
                      (d, fname),
                      file=sys.stderr)
                return False
            knownext = [ '.c', '.cc', '.cpp', '.java', '.py', '.py2', '.py3', '.cs' ]
            (base, ext) = os.path.splitext(fname)
            if ext not in knownext:
                print("ERROR: Unknown extension for submissions/%s/%s" %
                      (d, fname),
                      file=sys.stderr)
                return False
            copyfiles.append(os.path.join('submissions', d, fname))
            nsubmit += 1
            if d == 'accepted':
                naccept += 1

    print("found %d submissions, of which %d accepted" % (nsubmit, naccept))
    if naccept == 0:
        print("ERROR: No ACCEPTED solutions found", file=sys.stderr)
        return False

    # Find output validator.
    if custom_validator:
        have_validator = False
        if os.path.isdir(os.path.join(probdir, 'output_validators')):
            have_validator = True
            try:
                validator_files = os.listdir(os.path.join(probdir,
                                                          'output_validators'))
            except OSError as e:
                print("ERROR: Can not list output_validator files",
                      file=sys.stderr)
                print(e, file=sys.stderr)
                return False
            for fname in validator_files:
                if not os.path.isfile(os.path.join(probdir,
                                                   'output_validators', fname)):
                    print("ERROR: Unexpected non-file output_validators/%s" %
                          fname,
                          file=sys.stderr)
                    return False
                copyfiles.append(os.path.join('output_validators', fname))

        if not have_validator:
            print("ERROR: Missing output_validator", file=sys.stderr)
            return False

    # Build .ZIP file.
    print("writing ZIP file %s" % output)

    zf = zipfile.ZipFile(output,
                         mode="w",
                         compression=zipfile.ZIP_DEFLATED,
                         allowZip64=False)

    for fname in copyfiles:
        zf.write(os.path.join(probdir, fname),
                 fname,
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
def build_contest_zip(zipfiles, outfile):
    print("writing ZIP file %s" % outfile)

    zf = zipfile.ZipFile(outfile,
                         mode="w",
                         compression=zipfile.ZIP_DEFLATED,
                         allowZip64=False)

    for fname in zipfiles + ['contest.pdf', 'contest-web.pdf', 'solutions.pdf']:
        zf.write(fname,
                 fname,
                 compress_type=zipfile.ZIP_DEFLATED)

    print("done")
    print()

    zf.close()
