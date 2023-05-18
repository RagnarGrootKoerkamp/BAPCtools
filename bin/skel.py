import shutil
import sys
import datetime
import re

# Local imports
import config
from util import *
import contest

try:
    import questionary
    from questionary import Validator, ValidationError

    has_questionary = True

    class EmptyValidator(Validator):
        def validate(self, document):
            if len(document.text) == 0:
                raise ValidationError(message="Please enter a value")

except:
    has_questionary = False


def _ask_variable(name, default=None, allow_empty=False):
    while True:
        val = input(f"{name}: ")
        val = default if val == '' else val
        if val != '' or allow_empty:
            return val


def _ask_variable_string(name, default=None, allow_empty=False):
    if has_questionary:
        try:
            validate = None if allow_empty else EmptyValidator
            return questionary.text(
                name + ':', default=default or '', validate=validate
            ).unsafe_ask()
        except KeyboardInterrupt:
            fatal('Running interrupted')
    else:
        text = f' ({default})' if default else ''
        return _ask_variable(name + text, default if default else '', allow_empty)


def _ask_variable_bool(name, default=True):
    if has_questionary:
        try:
            return questionary.confirm(name + '?', default=default, auto_enter=False).unsafe_ask()
        except KeyboardInterrupt:
            fatal('Running interrupted')
    else:
        text = ' (Y/n)' if default else ' (y/N)'
        return _ask_variable(name + text, 'Y' if default else 'N').lower()[0] == 'y'


def _ask_variable_choice(name, choices, default=None):
    if has_questionary:
        try:
            plain = questionary.Style([('selected', 'noreverse')])
            return questionary.select(
                name + ':', choices=choices, default=default, style=plain
            ).unsafe_ask()
        except KeyboardInterrupt:
            fatal('Running interrupted')
    else:
        default = default or choices[0]
        text = f' ({default})' if default else ''
        return _ask_variable(name + text, default if default else '')


def _license_choices():
    return ['cc by-sa', 'cc by', 'cc0', 'public domain', 'educational', 'permission', 'unknown']


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


def new_contest():
    if config.args.contest:
        fatal('--contest does not work for new_contest.')
    if config.args.problem:
        fatal('--problem does not work for new_contest.')

    # Ask for all required infos.
    title = _ask_variable_string('name', config.args.contestname)
    subtitle = _ask_variable_string('subtitle', '', True).replace('_', '-')
    dirname = _ask_variable_string('dirname', _alpha_num(title))
    author = _ask_variable_string('author', f'The {title} jury').replace('_', '-')
    testsession = _ask_variable_bool('testsession', False)
    year = _ask_variable_string('year', str(datetime.datetime.now().year))
    source_url = _ask_variable_string('source url', '', True)
    license = _ask_variable_choice('license', _license_choices())
    rights_owner = _ask_variable_string('rights owner', 'author')
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

    statement_languages = config.args.language if config.args.language else ['en']

    problemname = {
        lang: config.args.problemname
        if config.args.problemname
        else _ask_variable_string(f'problem name ({lang})')
        for lang in statement_languages
    }
    dirname = (
        _alpha_num(problemname)
        if config.args.problemname
        else _ask_variable_string('dirname', _alpha_num(problemname[statement_languages[0]]))
    )
    author = config.args.author if config.args.author else _ask_variable_string('author')

    validator_flags = ''
    if config.args.validation:
        assert config.args.validation in ['default', 'custom', 'custom interactive']
        validation = config.args.validation
    else:
        validation = _ask_variable_choice(
            'validation', ['default', 'float', 'custom', 'custom interactive']
        )
        if validation == 'float':
            validation = 'default'
            validator_flags = 'validator_flags:\n  float_tolerance 1e-6\n'
            log(f'Using default float tolerance of 1e-6')

    # Read settings from the contest-level yaml file.
    variables = contest.contest_yaml()

    for k, v in {
        'problemname': problemname,
        'dirname': dirname,
        'author': author,
        'validation': validation,
        'validator_flags': validator_flags,
    }.items():
        variables[k] = v

    variables['source'] = _ask_variable_string(
        'source', variables.get('source', variables.get('name', '')), True
    )
    variables['source_url'] = _ask_variable_string(
        'source url', variables.get('source_url', ''), True
    )
    variables['license'] = _ask_variable_choice(
        'license', _license_choices(), variables.get('license', None)
    )
    variables['rights_owner'] = _ask_variable_string(
        'rights owner', variables.get('rights_owner', 'author')
    )

    # Copy tree from the skel directory, next to the contest, if it is found.
    skeldir, preserve_symlinks = get_skel_dir(target_dir)
    log(f'Copying {skeldir} to {target_dir/dirname}.')

    problems_yaml = target_dir / 'problems.yaml'

    if problems_yaml.is_file():
        if has_ryaml:
            data = read_yaml(problems_yaml) or []
            prev_label = data[-1]['label'] if data else None
            next_label = (
                ('X' if contest.contest_yaml().get('testsession') else 'A')
                if prev_label is None
                else inc_label(prev_label)
            )
            # Name and time limits are overridden by problem.yaml, but still required.
            data.append(
                {
                    'id': dirname,
                    'label': next_label,
                    'name': problemname,
                    'rgb': '#000000',
                    'time_limit': 1.0,
                }
            )
            write_yaml(data, problems_yaml)
        else:
            error('ruamel.yaml library not found. Please update problems.yaml manually.')

    copytree_and_substitute(
        skeldir, target_dir / dirname, variables, exist_ok=True, preserve_symlinks=preserve_symlinks
    )


def rename_problem(problem):
    if not has_ryaml:
        fatal('ruamel.yaml library not found.')

    newname = {
        lang: config.args.problemname
        if config.args.problemname
        else _ask_variable_string(f'New problem name ({lang})', problem.settings.name[lang])
        for lang in problem.statement_languages
    }
    dirname = (
        _alpha_num(config.args.problemname)
        if config.args.problemname
        else _ask_variable_string('dirname', _alpha_num(newname[problem.statement_languages[0]]))
    )

    shutil.move(problem.name, dirname)

    problem_yaml = Path(dirname) / 'problem.yaml'
    data = read_yaml(problem_yaml)
    data['name'] = newname
    write_yaml(data, problem_yaml)

    problems_yaml = Path('problems.yaml')
    if problems_yaml.is_file():
        data = read_yaml(problems_yaml) or []
        prob = next((p for p in data if p['id'] == problem.name), None)
        if prob is not None:
            prob['id'] = dirname
            prob['name'] = newname
            write_yaml(data, problems_yaml)


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
