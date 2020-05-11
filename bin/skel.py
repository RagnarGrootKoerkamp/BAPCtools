import shutil

import config
import datetime
import re

# Local imports
from util import *


# Returns the alphanumeric version of a string:
# This reduces it to a string that follows the regex:
# [a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]
def _alpha_num(string):
    s = re.sub(r'[^a-zA-Z0-9_.-]', '', string.lower().replace(' ', '').replace('-', ''))
    while s.startswith('_.-'):
        s = s[1:]
    while s.endswith('_.-'):
        s = s[:-1]
    return s


def _ask_variable(name, default=None):
    if default == None:
        val = ''
        while True:
            print(f"{name}: ", end='')
            val = input()
            if val == '':
                print(f"{name} must not be empty!")
            else:
                break
        return val
    else:
        print(f"{name} [{default}]: ", end='')
        val = input()
        return default if val == '' else val


# Returns the alphanumeric version of a string:
# This reduces it to a string that follows the regex:
# [a-zA-Z0-9][a-zA-Z0-9_.-]*[a-zA-Z0-9]
def alpha_num(string):
    s = re.sub(r'[^a-zA-Z0-9_.-]', '', string.lower().replace(' ', '').replace('-', ''))
    while s.startswith('_.-'):
        s = s[1:]
    while s.endswith('_.-'):
        s = s[:-1]
    return s


def new_contest(name):
    # Ask for all required infos.
    title = _ask_variable('name', name)
    subtitle = _ask_variable('subtitle', '')
    dirname = _ask_variable('dirname', _alpha_num(title))
    author = _ask_variable('author', f'The {title} jury')
    testsession = _ask_variable('testsession?', 'n (y/n)')[0] != 'n'  # boolean
    year = _ask_variable('year', str(datetime.datetime.now().year))
    source = _ask_variable('source', title)
    source_url = _ask_variable('source url', '')
    license = _ask_variable('license', 'cc by-sa')
    rights_owner = _ask_variable('rights owner', 'author')

    skeldir = config.tools_root / 'skel/contest'
    copytree_and_substitute(skeldir, Path(dirname), locals(), exist_ok=False)


def new_problem():
    problemname = config.args.problemname if config.args.problemname else _ask_variable(
        'problem name')
    dirname = _ask_variable('dirname', _alpha_num(problemname))
    author = config.args.author if config.args.author else _ask_variable(
        'author', config.args.author)

    if config.args.custom_validation:
        validation = 'custom'
    elif config.args.default_validation:
        validation = 'default'
    else:
        validation = _ask_variable('validation', 'default')

    # Read settings from the contest-level yaml file.
    variables = read_yaml(Path('contest.yaml'))

    for k, v in {
            'problemname': problemname,
            'dirname': dirname,
            'author': author,
            'validation': validation
    }.items():
        variables[k] = v

    for k in ['source', 'source_url', 'license', 'rights_owner']:
        if k not in variables: variables[k] = ''

    # Copy tree from the skel directory, next to the contest, if it is found.
    skeldir = config.tools_root / 'skel/problem'
    if Path('skel/problem').is_dir(): skeldir = Path('skel/problem')
    if Path('../skel/problem').is_dir(): skeldir = Path('../skel/problem')
    if config.args.skel: skeldir = Path(config.args.skel)
    print(f'Copying {skeldir} to {dirname}.')

    copytree_and_substitute(skeldir, Path(dirname), variables, exist_ok=True)


def new_cfp_problem(name):
    shutil.copytree(config.tools_root / 'skel/problem_cfp', name, symlinks=True)


def create_gitlab_jobs(contest, problems):
    def problem_source_dir(problem):
        return problem.resolve().relative_to(Path('..').resolve())

    header_yml = (config.tools_root / 'skel/gitlab-ci-header.yml').read_text()
    print(substitute(header_yml, locals()))

    contest_yml = (config.tools_root / 'skel/gitlab-ci-contest.yml').read_text()
    changes = ''
    for problem in problems:
        changes += '      - ' + str(problem_source_dir(problem)) + '/problem_statement/**/*\n'
    print(substitute(contest_yml, locals()))

    problem_yml = (config.tools_root / 'skel/gitlab-ci-problem.yml').read_text()
    for problem in problems:
        changesdir = problem_source_dir(problem)
        print('\n')
        print(substitute(problem_yml, locals()), end='')
