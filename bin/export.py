import datetime
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


# Replace \problemyamlname by the value of `name:` in problems.yaml in all .tex files.
def fix_problem_yaml_name(problem):
    reverts = []
    for f in (problem.path / 'problem_statement').iterdir():
        if f.is_file() and f.suffix == '.tex' and len(f.suffixes) >= 2:
            lang = f.suffixes[-2][1:]
            t = f.read_text()
            if r'\problemyamlname' in t:
                if lang in problem.settings.name:
                    reverts.append((f, t))
                    t = t.replace(r'\problemyamlname', problem.settings.name[lang])
                    f.write_text(t)
                else:
                    util.error(f'{f}: no name set for language {lang}.')

    def revert():
        for f, t in reverts:
            f.write_text(t)

    return revert


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


def build_problem_zip(problem, output):
    """Make DOMjudge ZIP file for specified problem."""

    if not problem.interactive:
        # Glob, required?
        files = [
            ('domjudge-problem.ini', False),  # DEPRECATED, may be removed at some point.
            ('problem.yaml', True),
            ('.timelimit', True),
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
            ('.timelimit', True),
            ('problem.pdf', True),
            ('problem_statement/*', True),
            # Either .interaction or .in.statement should be present, but we only care about .interaction here.
            ('data/sample/*.interaction', False),
            ('data/sample/*.in.statement', False),
            ('data/sample/*.ans.statement', False),
            ('data/secret/*.in', True),
            # Not really needed, but otherwise problemtools will complain.
            ('data/secret/*.ans', True),
            ('submissions/accepted/**/*', True),
            ('submissions/*/**/*', False),
            ('attachments/**/*', False),
        ]

    if 'custom' in problem.settings.validation:
        files.append(('output_validators/**/*', True))

    if config.args.kattis:
        files.append(('input_validators/**/*', True))

    print("Preparing to make ZIP file for problem dir %s" % problem.path, file=sys.stderr)

    # Build list of files to store in ZIP file.
    copyfiles = set()

    for pattern, required in files:
        # Only include hidden files if the pattern starts with a '.'.
        paths = list(util.glob(problem.path, pattern, include_hidden=pattern[0] == '.'))
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

    revert_problem_yaml_name = fix_problem_yaml_name(problem)

    try:
        zf = zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

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

    finally:
        revert_problem_yaml_name()

    return True


# Assumes the current working directory has: the zipfiles and
# contest.pdf
# contest-web.pdf
# solutions.pdf
# Output is <outfile>
def build_contest_zip(problems, zipfiles, outfile, args):
    print("writing ZIP file %s" % outfile, file=sys.stderr)

    update_problems_yaml(problems)

    zf = zipfile.ZipFile(outfile, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=False)

    for fname in zipfiles:
        zf.write(fname, fname, compress_type=zipfile.ZIP_DEFLATED)

    # For general zip export, also create pdfs and a samples zip.
    if not args.kattis:
        build_samples_zip(problems)

        for fname in [
            'problems.yaml',
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


def update_contest_id(cid):
    if has_ryaml:
        contest_yaml_path = Path('contest.yaml')
        data = read_yaml(contest_yaml_path)
        data['contest_id'] = cid
        write_yaml(data, contest_yaml_path)
    else:
        error('ruamel.yaml library not found. Update the id manually.')


def export_contest():
    data = contest_yaml()

    if not data:
        fatal('Exporting a contest only works if contest.yaml is available and not empty.')

    cid = get_contest_id()
    if cid:
        data['id'] = cid

    data['start_time'] = data['start_time'].isoformat() + ('+00:00' if has_ryaml else '')
    if not has_ryaml:
        for key in ('duration', 'scoreboard_freeze_duration'):
            if key in data:
                data[key] = str(datetime.timedelta(seconds=data[key]))

    verbose("Uploading contest.yaml:")
    verbose(data)
    r = call_api(
        'POST',
        '/contests',
        files={
            'yaml': (
                'contest.yaml',
                yaml.dump(data),
                'application/x-yaml',
            )
        },
    )
    if r.status_code == 400:
        fatal(parse_yaml(r.text)['message'])
    r.raise_for_status()

    new_cid = yaml.load(r.text, Loader=yaml.SafeLoader)
    log(f'Uploaded the contest to contest_id {new_cid}.')
    if new_cid != cid:
        log('Update contest_id in contest.yaml automatically? [Y/n]')
        a = input().lower()
        if a == '' or a[0] == 'y':
            update_contest_id(new_cid)
            log(f'Updated contest_id to {new_cid}')
    return new_cid


def update_problems_yaml(problems, colors=None):
    # Update name and timelimit values.
    if not has_ryaml:
        log(
            'ruamel.yaml library not found. Make sure to update the name and timelimit fields manually.'
        )
        return

    log('Updating problems.yaml')
    path = Path('problems.yaml')
    data = path.is_file() and read_yaml(path) or []

    change = False
    for problem in problems:
        found = False
        for d in data:
            if d['id'] == problem.name:
                found = True
                if problem.settings.name and problem.settings.name != d.get('name'):
                    change = True
                    d['name'] = problem.settings.name

                if 'rgb' not in d:
                    change = True
                    d['rgb'] = "#000000"

                if (
                    not problem.settings.timelimit_is_default
                    and problem.settings.timelimit != d.get('time_limit')
                ):
                    change = True
                    d['time_limit'] = problem.settings.timelimit
                break
        if not found:
            change = True
            log(f'Add problem {problem.name}')
            data.append(
                {
                    'id': problem.name,
                    'label': problem.label,
                    'name': problem.settings.name,
                    'rgb': '#000000',
                    'time_limit': problem.settings.timelimit,
                }
            )

    if colors:
        if len(data) != len(colors):
            warn(
                f'Number of colors ({len(colors)}) is not equal to the number of problems ({len(data)})'
            )
        for d, c in zip(data, colors):
            color = ('' if c.startswith('#') else '#') + c
            if 'rgb' not in d or d['rgb'] != color:
                change = True
            d['rgb'] = color

    if change:
        if config.args.action in ['update_problems_yaml']:
            a = 'y'
        else:
            log('Update problems.yaml with latest values? [Y/n]')
            a = input().lower()
        if a == '' or a[0] == 'y':
            write_yaml(data, path)
            log(f'Updated problems.yaml')
    else:
        if config.args.action == 'update_problems_yaml':
            log(f'Already up to date')


def export_problems(problems, cid):
    if not contest_yaml():
        fatal('Exporting a contest only works if contest.yaml is available and not empty.')

    update_problems_yaml(problems)

    # Uploading problems.yaml
    data = "".join(open("problems.yaml", "r").readlines())
    verbose("Uploading problems.yaml:")
    verbose(data)
    r = call_api(
        'POST',
        f'/contests/{cid}/problems/add-data',
        files={
            'data': (
                'problems.yaml',
                data,
                'application/x-yaml',
            )
        },
    )
    if r.status_code == 400:
        fatal(parse_yaml(r.text)['message'])
    r.raise_for_status()

    log(f'Uploaded problems.yaml for contest_id {cid}.')
    data = yaml.load(r.text, Loader=yaml.SafeLoader)
    return data  # Returns the API IDs of the added problems.


# Export a single problem to the specified contest ID.
def export_problem(problem, cid, pid):
    if pid:
        log(f'Export {problem.name} to id {pid}')
    else:
        log(f'Export {problem.name} to new id')

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
        files=[('zip', zipfile)],
    )
    yaml_response = yaml.load(r.text, Loader=yaml.SafeLoader)
    if 'messages' in yaml_response:
        verbose(f'RESPONSE:\n' + '\n'.join(yaml_response['messages']))
    elif 'message' in yaml_response:
        verbose(f'RESPONSE: ' + yaml_response['message'])
    else:
        verbose(f'RESPONSE:\n' + str(yaml_response))
    r.raise_for_status()


# Export the contest and individual problems to DOMjudge.
# Mimicked from https://github.com/DOMjudge/domjudge/blob/main/misc-tools/import-contest.sh
def export_contest_and_problems(problems):
    cid = contest_yaml().get('contest_id')
    if cid is not None and cid != '':
        log(f'Reusing contest id {cid} from contest.yaml')
    if not any(contest['id'] == cid for contest in get_contests()):
        cid = export_contest()

    def get_problems():
        r = call_api('GET', f'/contests/{cid}/problems')
        r.raise_for_status()
        return yaml.load(r.text, Loader=yaml.SafeLoader)

    # Query the internal DOMjudge problem IDs.
    ccs_problems = get_problems()
    if not ccs_problems:
        export_problems(problems, cid)
        # Need to query the API again, because `/problems/add-data` returns a list of IDs, not the full problem objects.
        ccs_problems = get_problems()

    check_if_user_has_team()

    def get_problem_id(problem):
        nonlocal ccs_problems
        for p in ccs_problems:
            if p['short_name'] == problem.name or p.get('externalid') == problem.name:
                return p['id']

    for problem in problems:
        pid = get_problem_id(problem)
        export_problem(problem, cid, pid)


def check_if_user_has_team():
    # Not using the /users/{uid} route, because {uid} is either numeric or a string depending on the DOMjudge config.
    r = call_api('GET', f'/users')
    r.raise_for_status()
    if not any(user['username'] == config.args.username and user['team'] for user in r.json()):
        warn(f'User "{config.args.username}" is not associated with a team.')
        warn('Therefore, the jury submissions will not be run by the judgehosts.')
        log('Continue export to DOMjudge? [N/y]')
        a = input().lower()
        if not a or a[0] != 'y':
            fatal('Aborted.')
