import config
import run
import random
import generate
import time

import parallel
from util import *

# STEPS:
# 1. Find generator invocations depending on {seed}.
# 2. Generate a testcase + .ans using the rule using a random seed.
# 3. Run all submissions against the generated testcase.
# 4. When at least one submissions fails: create a generated testcase:
#      data/fuzz/1.in: <generator rule with hardcoded seed>
#    by using a numbered directory data/fuzz.


def _save_test(problem, command):
    try:
        import ruamel.yaml
    except:
        error('Fuzzing needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.')
        return

    generators_yaml = problem.path / 'generators/generators.yaml'
    if not generators_yaml.is_file():
        generators_yaml.write_text('')

    # Round-trip parsing.
    yaml = ruamel.yaml.YAML(typ='rt')
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    data = yaml.load(generators_yaml)

    if data is None:
        data = ruamel.yaml.comments.CommentedMap()

    if ('data' not in data) or (data['data'] is None):
        data['data'] = ruamel.yaml.comments.CommentedMap()
    if ('fuzz' not in data['data']) or (data['data']['fuzz'] is None):
        data['data']['fuzz'] = ruamel.yaml.comments.CommentedMap()
    data['data']['fuzz']['type'] = 'directory'
    if ('data' not in data['data']['fuzz']) or (data['data']['fuzz']['data'] is None):
        data['data']['fuzz']['data'] = ruamel.yaml.comments.CommentedSeq()
    if not isinstance(data['data']['fuzz']['data'], ruamel.yaml.comments.CommentedSeq):
        fatal('data.fuzz.data must be a sequence, not a dictionary.')

    item = ruamel.yaml.comments.CommentedMap()
    item[''] = command
    data['data']['fuzz']['data'].append(item)

    # Overwrite generators.yaml.
    yaml.dump(data, generators_yaml)


def _try_generator_invocation(problem, t, submissions, i):
    generator = t.generator
    solution = t.config.solution

    # GENERATE THE TEST DATA
    cwd = problem.tmpdir / 'data' / 'fuzz'
    cwd.mkdir(parents=True, exist_ok=True)
    name = 'tmp'
    infile = cwd / (name + '.in')
    ansfile = cwd / (name + '.ans')

    assert generator.program is not None

    # Pick a random seed.
    seed = random.randint(0, 2 ** 31 - 1)

    command = generator.cache_command(seed=seed)

    bar = ProgressBar(
        'Fuzz ' + str(i) + ': ' + command, max_len=max(len(s.name) for s in submissions)
    )

    bar.start('generate')
    result = generator.run(bar, cwd, name, seed)
    if result.ok is not True:
        bar.finalize()
        return
    bar.done()

    testcase = run.Testcase(problem, infile, short_path=Path('fuzz') / (name + '.in'))

    # Validate the manual or generated .in.
    bar.start('validate input')
    if not testcase.validate_format('input_format', bar=bar, constraints=None):
        bar.finalize()
        return
    bar.done()

    # Generate .ans.
    if not problem.interactive:
        if solution and not testcase.ans_path.is_file():
            if testcase.ans_path.is_file():
                testcase.ans_path.unlink()
            # Run the solution and validate the generated .ans.
            bar.start('generate ans')
            if solution.run(bar, cwd, name).ok is not True:
                bar.finalize()
                return
            bar.done()

        if ansfile.is_file():
            bar.start('validate output')
            if not testcase.validate_format('output_format', bar=bar):
                bar.finalize()
                return
            bar.done()
        else:
            if not target_ansfile.is_file():
                bar.error(f'{ansfile.name} does not exist and was not generated.')
                bar.finalize()
                return
    else:
        if not testcase.ans_path.is_file():
            testcase.ans_path.write_text('')

    saved = False

    def run_submission(submission):
        nonlocal saved
        r = run.Run(problem, submission, testcase)
        localbar = bar.start(submission)
        result = r.run()
        if result.verdict != 'ACCEPTED':
            if not saved:
                saved = True
                localbar.error('Broken! Saving testcase in generators.yaml.')
                _save_test(problem, command)
                return
        localbar.done()

    # Run all submissions against the testcase.
    in_parallel = True
    if problem.interactive:
        in_parallel = False
        verbose('Disabling parallelization for interactive problem.')
    p = parallel.Parallel(run_submission, in_parallel)
    for submission in submissions:
        p.put(submission)
    p.done()
    bar.global_logged = False
    bar.finalize(print_done=False)


def fuzz(problem):
    try:
        import ruamel.yaml
    except:
        error('Fuzzing needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.')
        return

    # config.args.no_bar = True

    # GENERATOR INVOCATIONS
    generator_config = generate.GeneratorConfig(problem)
    if not generator_config.ok:
        return False

    # Filter to only keep rules depending on seed.
    def filter_dir(d):
        d.data = list(
            filter(
                lambda t: isinstance(t, generate.Directory)
                or (not t.manual and t.generator.uses_seed),
                d.data,
            )
        )

    testcase_rules = []
    generator_config.root_dir.walk(
        lambda t: testcase_rules.append(t), dir_f=filter_dir, dir_last=False
    )

    if len(testcase_rules) == 0:
        fatal('No invocations depending on {seed} found.')

    generator_config.build(build_visualizers=False)
    problem.validators('output')

    # SUBMISSIONS
    submissions = problem.submissions(accepted_only=True)

    if len(submissions) == 0:
        fatal('No submissions found.')

    tstart = time.monotonic()
    i = 0
    while True:
        for testcase_rule in testcase_rules:
            if time.monotonic() - tstart > config.args.time:
                return True
            i += 1
            _try_generator_invocation(problem, testcase_rule, submissions, i)
