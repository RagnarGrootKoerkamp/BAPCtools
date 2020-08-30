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
    if config.args.contest:
        fatal('--contest does not work for new_contest.')
    if config.args.problem:
        fatal('--problem does not work for new_contest.')

    # Ask for all required infos.
    title = _ask_variable('name', name)
    subtitle = _ask_variable('subtitle', '').replace('_', '-')
    dirname = _ask_variable('dirname', _alpha_num(title))
    author = _ask_variable('author', f'The {title} jury').replace('_', '-')
    testsession = _ask_variable('testsession?', 'n (y/n)')[0] != 'n'  # boolean
    year = _ask_variable('year', str(datetime.datetime.now().year))
    source = _ask_variable('source', title)
    source_url = _ask_variable('source url', '')
    license = _ask_variable('license', 'cc by-sa')
    rights_owner = _ask_variable('rights owner', 'author')
    title = title.replace('_', '-')

    skeldir = config.tools_root / 'skel/contest'
    log(f'Copying {skeldir} to {dirname}.')
    copytree_and_substitute(skeldir,
                            Path(dirname),
                            locals(),
                            exist_ok=False,
                            preserve_symlinks=False)

def get_skel_dir(target_dir):
    skeldir = config.tools_root / 'skel/problem'
    preserve_symlinks = False
    if (target_dir / 'skel/problem').is_dir():
        skeldir = target_dir / 'skel/problem'
        preserve_symlinks = True
    if (target_dir / '../skel/problem').is_dir():
        skeldir = target_dir / '../skel/problem'
        preserve_symlinks = True
    if config.args.skel:
        skeldir = Path(config.args.skel)
        preserve_symlinks = True
    return (skeldir, preserve_symlinks)


def new_problem():
    target_dir = Path('.')
    if config.args.contest:
        target_dir = Path(config.args.contest)
    if config.args.problem:
        fatal('--problem does not work for new_problem.')

    problemname = config.args.problemname if config.args.problemname else _ask_variable(
        'problem name')
    dirname = _alpha_num(problemname) if config.args.problemname else _ask_variable(
        'dirname', _alpha_num(problemname))
    author = config.args.author if config.args.author else _ask_variable(
        'author', config.args.author)

    if config.args.validation:
        assert config.args.validation in ['default', 'custom', 'custom interactive']
        validation = config.args.validation
    else:
        validation = _ask_variable('validation (default/custom/custom interactive)', 'default')

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
    skeldir, preserve_symlinks = get_skel_dir(target_dir)
    log(f'Copying {skeldir} to {target_dir/dirname}.')

    problems_yaml = target_dir / 'problems.yaml'

    if problems_yaml.is_file():
        problems_yaml.write_text(problems_yaml.read_text() + '- id: ' + dirname + '\n')

    copytree_and_substitute(skeldir,
                            target_dir / dirname,
                            variables,
                            exist_ok=True,
                            preserve_symlinks=preserve_symlinks)


def copy_skel_dir(problems):
    assert len(problems)==1
    problem = problems[0]

    skeldir, preserve_symlinks = get_skel_dir(problem.path)

    for d in config.args.directory:
        d = Path(d)
        sources = [skeldir / d, skeldir / d.parent  / (d.name + '.template')]
        target = problem.path / d

        if d.is_absolute():
            error(f'{d} is not a relative path.')
            continue

        found = False
        for source in sources:
            if not source.is_file() and not source.is_dir():
                continue

            target.mkdir(exist_ok=True, parents=True)
            copytree_and_substitute(source,
                                target,
                                None,
                                exist_ok=True,
                                preserve_symlinks=preserve_symlinks)
            found = True
            break

        if not found:
            error(f'{source} does not exist')




def create_gitlab_jobs(contest, problems):
    def problem_source_dir(problem):
        return problem.path.resolve().relative_to(Path('..').resolve())

    header_yml = (config.tools_root / 'skel/gitlab_ci/header.yaml').read_text()
    print(substitute(header_yml, locals()))

    contest_yml = (config.tools_root / 'skel/gitlab_ci/contest.yaml').read_text()
    changes = ''
    for problem in problems:
        changes += '      - ' + str(problem_source_dir(problem)) + '/problem_statement/**/*\n'
    print(substitute(contest_yml, locals()))

    problem_yml = (config.tools_root / 'skel/gitlab_ci/problem.yaml').read_text()
    for problem_obj in problems:
        changesdir = problem_source_dir(problem_obj)
        problem = problem_obj.name
        print('\n')
        print(substitute(problem_yml, locals()), end='')
