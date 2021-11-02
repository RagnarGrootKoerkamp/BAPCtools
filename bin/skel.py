import shutil
import sys
import datetime
import re

# Local imports
import config
from util import *
import contest


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
            print(f"{name}: ", end='', file=sys.stderr)
            val = input()
            if val == '':
                print(f"{name} must not be empty!", file=sys.stderr)
            else:
                break
        return val
    else:
        print(f"{name} [{default}]: ", end='', file=sys.stderr)
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
    source_url = _ask_variable('source url', '')
    license = _ask_variable('license', 'cc by-sa')
    rights_owner = _ask_variable('rights owner', 'author')
    title = title.replace('_', '-')

    skeldir = config.tools_root / 'skel/contest'
    log(f'Copying {skeldir} to {dirname}.')
    copytree_and_substitute(
        skeldir, Path(dirname), locals(), exist_ok=False, preserve_symlinks=False
    )


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

    problemname = (
        config.args.problemname if config.args.problemname else _ask_variable('problem name')
    )
    dirname = (
        _alpha_num(problemname)
        if config.args.problemname
        else _ask_variable('dirname', _alpha_num(problemname))
    )
    author = (
        config.args.author if config.args.author else _ask_variable('author', config.args.author)
    )

    if config.args.validation:
        assert config.args.validation in ['default', 'custom', 'custom interactive']
        validation = config.args.validation
    else:
        validation = _ask_variable('validation (default/custom/custom interactive)', 'default')

    # Read settings from the contest-level yaml file.
    variables = contest.contest_yaml() or {}
    if 'source' not in variables:
        variables['source'] = variables.get('name', '')

    for k, v in {
        'problemname': problemname,
        'dirname': dirname,
        'author': author,
        'validation': validation,
    }.items():
        variables[k] = v

    for k in ['source_url', 'license', 'rights_owner']:
        if k not in variables:
            variables[k] = ''

    # Copy tree from the skel directory, next to the contest, if it is found.
    skeldir, preserve_symlinks = get_skel_dir(target_dir)
    log(f'Copying {skeldir} to {target_dir/dirname}.')

    problems_yaml = target_dir / 'problems.yaml'

    if problems_yaml.is_file():
        try:
            import ruamel.yaml

            ryaml = ruamel.yaml.YAML(typ='rt')
            ryaml.default_flow_style = False
            ryaml.indent(mapping=2, sequence=4, offset=2)
            data = ryaml.load(problems_yaml) or []
            next_label = contest.next_label(data[-1]['label'] if data else None)
            # Name and timelimits are overridden by problem.yaml, but still required.
            data.append(
                {
                    'id': dirname,
                    'name': problemname,
                    'label': next_label,
                    'rgb': '#000000',
                    'timelimit': 1.0,
                }
            )
            ryaml.dump(
                data,
                problems_yaml,
                # Remove spaces at the start of each (non-commented) line, caused by the indent configuration.
                # If there was a top-level key (like `problems:`), this wouldn't be needed...
                # See also: https://stackoverflow.com/a/58773229
                transform=lambda yaml_str: "\n".join(
                    line if line.strip().startswith('#') else line[2:]
                    for line in yaml_str.split("\n")
                ),
            )
        except NameError as e:
            error('ruamel.yaml library not found. Please update problems.yaml manually.')

    copytree_and_substitute(
        skeldir, target_dir / dirname, variables, exist_ok=True, preserve_symlinks=preserve_symlinks
    )


def copy_skel_dir(problems):
    assert len(problems) == 1
    problem = problems[0]

    skeldir, preserve_symlinks = get_skel_dir(problem.path)

    for d in config.args.directory:
        d = Path(d)
        sources = [skeldir / d, skeldir / d.parent / (d.name + '.template')]
        target = problem.path / d

        if d.is_absolute():
            error(f'{d} is not a relative path.')
            continue

        found = False
        for source in sources:
            if not source.is_file() and not source.is_dir():
                continue

            target.parent.mkdir(exist_ok=True, parents=True)
            copytree_and_substitute(
                source, target, None, exist_ok=True, preserve_symlinks=preserve_symlinks
            )
            found = True
            break

        if not found:
            error(f'{source} does not exist')


# NOTE: This is one of few places that prints to stdout instead of stderr.
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
