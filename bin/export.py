import sys
import argparse
import os
import yaml
import os.path
import re
import zipfile
import config
import util
import base64
from pathlib import Path

from contest import *

try:
    import requests
except:
    pass

try:
    import ruamel.yaml
except:
    pass


# Replace \problemyamlname by the value of `name:` in problemset.yaml in all .tex files.
def fix_problem_yaml_name(problem):
    for f in (problem.path / 'problem_statement').iterdir():
        if f.is_file() and f.suffix == '.tex':
            t = f.read_text()
            if r'\problemyamlname' in t:
                t = t.replace(r'\problemyamlname', problem.settings.name)
                f.write_text(t)


def build_samples_zip(problems):
    zf = zipfile.ZipFile(
        'samples.zip', mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False
    )
    for fname in ['contest.pdf', 'contest-web.pdf']:
        if Path(fname).is_file():
            zf.write(fname, fname, compress_type=zipfile.ZIP_DEFLATED)

    for problem in problems:
        outputdir = Path(problem.label)

        attachments_dir = problem.path / 'attachments'
        if problem.interactive and not attachments_dir.is_dir():
            util.error(
                f'Interactive problem {problem.name} does not have an attachments/ directory.'
            )
            continue

        empty = True

        # Add attachments if they exist.
        if attachments_dir.is_dir():
            for f in attachments_dir.iterdir():
                if f.is_dir():
                    util.error(f'{f} directory attachments are not yet supported.')
                elif f.is_file() and f.exists():
                    zf.write(f, outputdir / f.name)
                    empty = False
                else:
                    util.error(f'Cannot include broken file {f}.')

        # Add samples for non-interactive problems.
        if not problem.interactive:
            samples = problem.testcases(needans=True, only_sample=True)
            for i in range(0, len(samples)):
                sample = samples[i]
                basename = outputdir / str(i + 1)
                zf.write(sample.in_path, basename.with_suffix('.in'))
                zf.write(sample.ans_path, basename.with_suffix('.ans'))
                empty = False

        if empty:
            util.error(f'No attachments or samples found for problem {problem.name}.')

    zf.close()
    print("Wrote zip to samples.zip", file=sys.stderr)


def build_problem_zip(problem, output, settings):
    """Make DOMjudge ZIP file for specified problem."""

    if not problem.interactive:
        # Glob, required?
        files = [
            ('domjudge-problem.ini', False),  # DEPRECATED, may be removed at some point.
            ('problem.yaml', True),
            ('problem.pdf', True),
            ('problem_statement/*', True),
            ('data/sample/*.in', True),
            ('data/sample/*.ans', True),
            ('data/secret/*.in', True),
            ('data/secret/*.ans', True),
            ('submissions/accepted/**/*', True),
            ('submissions/*/**/*', False),
            ('attachments/**/*', False),
        ]
    else:
        files = [
            ('domjudge-problem.ini', False),  # DEPRECATED, may be removed at some point.
            ('problem.yaml', True),
            ('problem.pdf', True),
            ('problem_statement/*', True),
            ('data/sample/*.interaction', True),
            ('data/secret/*.in', True),
            # Not really needed, but otherwise problemtools will complain.
            ('data/secret/*.ans', True),
            ('submissions/accepted/**/*', True),
            ('submissions/*/**/*', False),
            ('attachments/**/*', False),
        ]

    if 'custom' in settings.validation:
        files.append(('output_validators/**/*', True))

    if config.args.kattis:
        files.append(('input_validators/**/*', True))

    print("Preparing to make ZIP file for problem dir %s" % problem.path, file=sys.stderr)

    fix_problem_yaml_name(problem)

    # Build list of files to store in ZIP file.
    copyfiles = set()

    for pattern, required in files:
        paths = list(util.glob(problem.path, pattern))
        if required and len(paths) == 0:
            util.error(f'No matches for required path {pattern}.')
        for f in paths:
            # NOTE: Directories are skipped because ZIP only supports files.
            if f.is_file():
                out = f.relative_to(problem.path)
                # For Kattis, prepend the problem shortname to all files.
                if config.args.kattis:
                    out = problem.name / out
                copyfiles.add((f, out))

    # Build .ZIP file.
    print("writing ZIP file:", output, file=sys.stderr)

    zf = zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    # For kattis, write to problemname/<file> instead of just <file>.
    root = ''
    if config.args.kattis:
        root = os.path.basename(os.path.normpath(problem.path))
        root = re.sub(r'[^a-z0-9]', '', root.lower())
    for fname in sorted(copyfiles):
        source = fname
        target = fname
        if isinstance(fname, tuple):
            source = fname[0]
            target = fname[1]
        zf.write(source, target, compress_type=zipfile.ZIP_DEFLATED)

    # Done.
    zf.close()
    print("done", file=sys.stderr)
    print(file=sys.stderr)

    return True


# Assumes the current working directory has: the zipfiles and
# contest.pdf
# contest-web.pdf
# solutions.pdf
# Output is <outfile>
def build_contest_zip(problems, zipfiles, outfile, args):
    print("writing ZIP file %s" % outfile, file=sys.stderr)

    zf = zipfile.ZipFile(outfile, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    for fname in zipfiles:
        zf.write(fname, fname, compress_type=zipfile.ZIP_DEFLATED)

    # For general zip export, also create pdfs and a samples zip.
    if not args.kattis:
        build_samples_zip(problems)

        for fname in [
            'problemset.yaml',
            'contest.yaml',
            'contest.pdf',
            'contest-web.pdf',
            'solutions.pdf',
            'solutions-web.pdf',
            'samples.zip',
        ]:
            if Path(fname).is_file():
                zf.write(fname, fname, compress_type=zipfile.ZIP_DEFLATED)

    # For Kattis export, delete the original zipfiles.
    if args.kattis:
        for fname in zipfiles:
            fname.unlink()

    print("done", file=sys.stderr)
    print(file=sys.stderr)

    zf.close()


def call_api(method, endpoint, **kwargs):
    url = get_api() + endpoint
    verbose(f'{method} {url}')
    return requests.request(
        method,
        url,
        auth=requests.auth.HTTPBasicAuth(config.args.username, config.args.password),
        **kwargs,
    )


def update_contest_id(cid):
    try:
        ryaml = ruamel.yaml.YAML(typ='rt')
    except:
        error('ruamel.yaml library not found. Update the id manually.')
    ryaml.default_flow_style = False
    ryaml.indent(mapping=2, sequence=4, offset=2)
    contest_yaml_path = Path('contest.yaml')
    data = ryaml.load(contest_yaml_path)
    data['contest_id'] = cid
    ryaml.dump(data, contest_yaml_path)


def export_contest(problems):
    if contest_yaml() is None or problemset_yaml() is None:
        fatal(
            'Exporting a contest only works if both contest.yaml and problemset.yaml are available.'
        )

    def get_problem_label(name):
        for problem in problems:
            if problem.name == name:
                return problem.label
        fatal(f'Did not find problem {name}')

    def fix_letters():
        log('problemset.yaml is missing labels. Adding them.')
        try:
            ryaml = ruamel.yaml.YAML(typ='rt')
        except NameError:
            fatal('ruamel.yaml library not found. Update the labels manually.')
        ryaml.default_flow_style = False
        ryaml.indent(mapping=2, sequence=4, offset=2)
        path = Path('problemset.yaml')
        data = ryaml.load(path)
        for problem in data['problems']:
            if 'letter' not in problem:
                problem['letter'] = get_problem_label(problem['short-name'])

        ryaml.dump(data, path)

    # Make sure the problemset.yaml contains all required fields.
    for problem in problemset_yaml()['problems']:
        if 'letter' not in problem:
            fix_letters()
            break

    # Read set of problems
    try:
        r = call_api(
            'POST',
            '/contests',
            files={
                'yaml': (
                    'combined.yaml',
                    yaml.dump({**contest_yaml(), **problemset_yaml()}),
                    'application/x-yaml',
                )
            },
        )
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        msg = parse_yaml(r.text)
        if msg is not None and 'message' in msg:
            msg = msg['message']
        fatal(f'{msg}\n{e}')
    cid = yaml.load(r.text, Loader=yaml.SafeLoader)
    log(f'Uploaded the contest to contest_id {cid}. Please update this in contest.yaml.')
    log('Update contest_id automatically? [Y/n]')
    a = input().lower()
    debug(f'input: {a}')
    if a == '' or a[0] == 'y':
        update_contest_id(cid)
        log(f'Updated contest_id to {cid}')
    return cid


# Export a single problem to the specified contest ID.
def export_problem(problem, cid, pid):
    log(f'Export {problem.name} to id {pid}')
    zipfile = Path(problem.name).with_suffix('.zip')
    if not zipfile.is_file():
        error(f'Did not find {zipfile}. First run `bt zip`.')
        return
    data = None if pid is None else {'problem': pid}
    zip_path = Path(problem.name).with_suffix('.zip')
    zipfile = zip_path.open('rb')
    r = call_api(
        'POST',
        f'/contests/{cid}/problems',
        data=data,
        files=[('zip[]', zipfile)],
    )
    verbose(f'RESPONSE:\n' + '\n'.join(yaml.load(r.text, Loader=yaml.SafeLoader)['messages']))
    r.raise_for_status()


# Export the contest and individual problems to DOMjudge.
# Mimicked from https://github.com/DOMjudge/domjudge/blob/main/misc-tools/import-contest.sh
def export_contest_and_problems(problems):
    cid = contest_yaml().get('contest_id', None)
    if cid is not None and cid != '':
        log(f'Reusing contest id {cid} from contest.yaml')
    else:
        cid = export_contest(problems)

    # Query the internal DOMjudge problem IDs.
    r = call_api('GET', f'/contests/{cid}/problems')
    r.raise_for_status()
    ccs_problems = yaml.load(r.text, Loader=yaml.SafeLoader)
    debug(f'CURRENT PROBLEMS: {ccs_problems}')

    # TODO: Make sure the user is associated to a team.

    def get_problem_id(problem):
        nonlocal ccs_problems
        for p in ccs_problems:
            if p['short_name'] == problem.name or p.get('externalid', None) == problem.name:
                return p['id']

    for problem in problems:
        pid = get_problem_id(problem)
        export_problem(problem, cid, pid)
