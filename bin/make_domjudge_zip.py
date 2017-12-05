#!/usr/bin/python3

"""
Make a DOMjudge ZIP file for the specified problem.

Usage: make_domjudge_zip.py <options>

  --probdir         Path to problem directory in repository
  --output X.zip    Output file name for ZIP file

This tool only works under Linux.
"""

import sys
import argparse
import os
import os.path
import re
import zipfile


def checkInOutFile(probdir, fname):
    """Check format of input/output file."""

    with open(os.path.join(probdir, fname), "rb") as f:
        s = f.read()

    ok = True

    for c in s:
        if c != ord('\n') and (c < ord(' ') or c > ord('~')):
            print("%s: WARNING, strange character chr(%d)" % (fname, c))
            ok = False
            break

    if s.startswith(b' ') or s.find(b'\n ') >= 0:
        print("%s: WARNING, found leading space" % fname)
        ok = False

    if s.find(b' \n') >= 0 or s.endswith(b' '):
        print("%s: WARNING, found trailing space" % fname)
        ok = False

    if s.find(b'  ') >= 0:
        print("%s: WARNING, found double space" % fname)
        ok = False

    if s.startswith(b'\n') or s.find(b'\n\n') >= 0:
        print("%s: WARNING, found empty line" % fname)
        ok = False

    if not s.endswith(b'\n'):
        print("%s: WARNING, last line not terminated" % fname)
        ok = False


def make_domjudge_zip(probdir, output):
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
                if 'validation' in s and 'custom' in s:
                    custom_validator = True
    else:
        print("WARNING: Can not find problem.yaml file",
              file=sys.stderr)

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

        # Check format of input/output files.
        for tc in testcases:
            checkInOutFile(probdir, os.path.join(prefix, tc + '.in'))
            checkInOutFile(probdir, os.path.join(prefix, tc + '.ans'))

        # Add input/output files to list of files to copy to ZIP.
        for fname in inoutfiles:
            copyfiles.append(os.path.join(prefix, fname))

    # Find solutions.
    submit_types = [ 'ACCEPTED', 'WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED',
                     'RUN_TIME_ERROR' ]
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
            if d == 'ACCEPTED':
                naccept += 1

    print("found %d submissions, of which %d accepted" % (nsubmit, naccept))
    if naccept == 0:
        print("ERROR: No ACCEPTED solutions found", file=sys.stderr)
        return False

    # Find output validator.
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

    if custom_validator and not have_validator:
        print("WARNING: Missing output_validators directory",
              file=sys.stderr)

    if have_validator and not custom_validator:
        print("WARNING: Found unused output_validators directory",
              file=sys.stderr)

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


def main():

    parser = argparse.ArgumentParser()
    parser.format_help  = lambda: __doc__
    parser.format_usage = lambda: __doc__
    parser.add_argument('--probdir', action='store', type=str, required=True)
    parser.add_argument('--output', action='store', type=str, required=True)

    args = parser.parse_args()

    if not make_domjudge_zip(args.probdir, args.output):
        sys.exit(1)


if __name__ == '__main__':
    main()

