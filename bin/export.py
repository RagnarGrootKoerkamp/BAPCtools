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
    copyfiles = []

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
        print("ERROR: Can not find domjudge-problem.ini file", file=sys.stderr)
        return False

    if os.path.isfile(os.path.join(probdir, 'problem.yaml')):
        copyfiles.append('problem.yaml')

        # Scan problem.yaml file to decide if a custom validator is used.
        with open(os.path.join(probdir, 'problem.yaml')) as f:
            for s in f:
                if 'validation' in s and 'custom' in s and 'default' not in s:
                    custom_validator = True
    else:
        print("WARNING: Can not find problem.yaml file", file=sys.stderr)

    if os.path.isfile(os.path.join(probdir, 'problem.pdf')):
        copyfiles.append('problem.pdf')
    else:
        print("WARNING: Can not find problem.pdf file", file=sys.stderr)

    if os.path.isfile(os.path.join(probdir, 'problem_statement/problem.tex')):
        copyfiles.append('problem_statement/problem.tex')
    else:
        print("WARNING: Can not find problem.tex file", file=sys.stderr)

    for f in os.listdir(os.path.join(probdir, 'problem_statement')):
        if os.path.splitext(f)[1] in ['.jpg', '.svg', '.png', '.pdf']:
            copyfiles.append('problem_statement/' + f)

    # Find input/output files.
    for (prefix, typ) in (('data/sample', 'sample'), ('data/secret', 'secret')):

        try:
            inoutfiles = os.listdir(os.path.join(probdir, prefix))
        except OSError as e:
            print("ERROR: Can not find %s input/output files" % typ, file=sys.stderr)
            print(e, file=sys.stderr)
            return False

        # Check pairs of input/output files.
        inoutfiles.sort()
        testcases = list(set([os.path.splitext(fname)[0] for fname in inoutfiles]))

        # Check pair of .in and .ans exists for every testcase.
        filtered = []
        for tc in testcases:
            if tc[0] == '.':
                continue
            if '.' in tc:
                print("ERROR: Bad testcase name %s/%s" % (prefix, tc), file=sys.stderr)
                return False
            if not os.path.isfile(os.path.join(probdir, prefix, tc + '.in')):
                print("ERROR: Missing file %s/%s" % (prefix, tc + '.in'), file=sys.stderr)
                return False
            if not os.path.isfile(os.path.join(probdir, prefix, tc + '.ans')):
                print("ERROR: Missing file %s/%s" % (prefix, tc + '.ans'), file=sys.stderr)
                return False
            filtered.append(tc)
        testcases = filtered

        print("found %d %s test cases" % (len(testcases), typ))

        if len(testcases) == 0:
            print("ERROR: No %s input/output files found" % typ, file=sys.stderr)
            return False

        # Add input/output files to list of files to copy to ZIP.
        for fname in inoutfiles:
            copyfiles.append(os.path.join(prefix, fname))

    # Find solutions.
    submit_types = ['accepted', 'wrong_answer', 'time_limit_exceeded', 'run_time_error']
    try:
        for d in os.listdir(os.path.join(probdir, 'submissions')):
            if d not in submit_types:
                print("ERROR: Found unexpected entry submissions/%s" % d, file=sys.stderr)
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
            if fname[0] == '.':
                continue
            if not os.path.isfile(os.path.join(probdir, 'submissions', d, fname)):
                print("ERROR: Unexpected non-file submissions/%s/%s" % (d, fname), file=sys.stderr)
                return False
            knownext = ['.c', '.cc', '.cpp', '.java', '.py', '.py2', '.py3', '.cs']
            (base, ext) = os.path.splitext(fname)
            if ext not in knownext:
                print(
                    "ERROR: Unknown extension for submissions/%s/%s" % (d, fname), file=sys.stderr)
                return False
            copyfiles.append(os.path.join('submissions', d, fname))
            nsubmit += 1
            if d == 'accepted':
                naccept += 1

    print("found %d submissions, of which %d accepted" % (nsubmit, naccept))
    if naccept == 0:
        print("ERROR: No ACCEPTED solutions found", file=sys.stderr)
        return False

    # Find input validator.
    # With the Kattis flag, This adds an extra directory layer so that included
    # headers are found.
    # TODO(ragnar): copy included headers as well, but only when needed.
    have_validator = False
    if os.path.isdir(os.path.join(probdir, 'input_validators')):
        try:
            validator_files = os.listdir(os.path.join(probdir, 'input_validators'))
        except OSError as e:
            print("ERROR: Can not list input_validator files", file=sys.stderr)
            print(e, file=sys.stderr)
            return False
        for fname in validator_files:
            have_validator = True
            if not os.path.isfile(os.path.join(probdir, 'input_validators', fname)):
                print("ERROR: Unexpected non-file input_validators/%s" % fname, file=sys.stderr)
                return False
            source = os.path.join('input_validators', fname)
            if args.kattis:
                target = os.path.join('input_format_validators', 'input_validator', fname)
                copyfiles.append((source, target))
            else:
                copyfiles.append(source)

    if not have_validator:
        print("ERROR: Missing input_validator", file=sys.stderr)
        return False

    # Find output validator.
    # With the Kattis flag, This adds an extra directory layer so that included
    # headers are found.
    if custom_validator:
        have_validator = False
        if os.path.isdir(os.path.join(probdir, 'output_validators')):
            try:
                validator_files = os.listdir(os.path.join(probdir, 'output_validators'))
            except OSError as e:
                print("ERROR: Can not list output_validator files", file=sys.stderr)
                print(e, file=sys.stderr)
                return False
            for fname in validator_files:
                have_validator = True
                if not os.path.isfile(os.path.join(probdir, 'output_validators', fname)):
                    print(
                        "ERROR: Unexpected non-file output_validators/%s" % fname, file=sys.stderr)
                    return False
                source = os.path.join('output_validators', fname)
                if args.kattis:
                    target = os.path.join('output_validators', 'output_validator', fname)
                    copyfiles.append((source, target))
                else:
                    copyfiles.append(source)

        if not have_validator:
            print("ERROR: Missing output_validator", file=sys.stderr)
            return False

    # Build .ZIP file.
    print("writing ZIP file %s" % output)

    zf = zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    # For kattis, write to problemname/<file> instead of just <file>.
    root = ''
    if args.kattis:
        root = os.path.basename(os.path.normpath(probdir))
        root = re.sub(r'[^a-z0-9]', '', root.lower())
    for fname in copyfiles:
        source = fname
        target = fname
        if isinstance(fname, tuple):
            source = fname[0]
            target = fname[1]
        zf.write(
            os.path.join(probdir, source),
            os.path.join(root, target),
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
        for fname in ['contest.pdf', 'contest-web.pdf', 'solutions.pdf']:
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

    # make a problem statement with problem.en.tex -> problem.tex,
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

    assert "problem.tex" in files

    # remember: current wd is st
    for f in files:
        if f != "problem.tex":
            symlink_quiet(os.path.join(orig_path, pst, f), os.path.join(st, f))

    source = os.path.join(problem, pst, 'problem.tex')
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
