import config
import run
import random
import generate
import time
import threading

import parallel
from util import *

# STEPS:
# 1. Find generator invocations depending on {seed}.
# 2. Generate a testcase + .ans using the rule using a random seed.
# 3. Run all submissions against the generated testcase.
# 4. When at least one submissions fails: create a generated testcase:
#      data/fuzz/1.in: <generator rule with hardcoded seed>
#    by using a numbered directory data/fuzz.

class Fuzz:
    def __init__(self, problem):
        self.generators_yaml_mutex = threading.Lock()
        self.problem = problem

        # GENERATOR INVOCATIONS
        generator_config = generate.GeneratorConfig(problem)
        self.testcase_rules = []
        if generator_config.ok:
            # Filter to only keep rules depending on seed.
            def filter_dir(d):
                d.data = list(
                    filter(
                        lambda t: isinstance(t, generate.Directory)
                        or (not t.manual and t.generator.uses_seed),
                        d.data,
                    )
                )

            
            generator_config.root_dir.walk(
                lambda t: self.testcase_rules.append(t), dir_f=filter_dir, dir_last=False
            )
            generator_config.build(build_visualizers=False)

        # BUILD VALIDATORS
        problem.validators('output')

        # SUBMISSIONS
        self.submissions = problem.submissions(accepted_only=True)

    def run(self):
        if not has_ryaml:
            error('Fuzzing needs the ruamel.yaml python3 library. Install python[3]-ruamel.yaml.')
            return False

        if len(self.testcase_rules) == 0:
            error('No invocations depending on {seed} found.')
            return False


        if len(self.submissions) == 0:
            error('No submissions found.')
            return False

        self.max_submission_len = max(len(s.name) for s in self.submissions)

        # config.args.no_bar = True
        tstart = time.monotonic()
        i = 0
        
        while True:
            for testcase_rule in self.testcase_rules:
                if time.monotonic() - tstart > config.args.time:
                    return True
                i += 1
                self._run_generator(testcase_rule, i)

    def _save_test(self, command):
        with self.generators_yaml_mutex:
            generators_yaml = self.problem.path / 'generators/generators.yaml'
            data = None
            if generators_yaml.is_file():
                data = read_yaml(generators_yaml)
            if data is None:
                data = ruamel.yaml.comments.CommentedMap()

            def get_or_add(yaml, key, t=ruamel.yaml.comments.CommentedMap):
                assert isinstance(data, ruamel.yaml.comments.CommentedMap)
                if not key in yaml or yaml[key] is None:
                    yaml[key] = t()
                assert isinstance(yaml[key], t)
                return yaml[key]

            parent = get_or_add(data, 'data')
            parent = get_or_add(parent, 'fuzz')
            entry = get_or_add(parent, 'data', ruamel.yaml.comments.CommentedSeq)

            entry.append(ruamel.yaml.comments.CommentedMap())
            entry[-1][''] = command

            # Overwrite generators.yaml.
            write_yaml(data, generators_yaml)

    def _run_generator(self, t, i):
        generator = t.generator
        solution = t.config.solution

        # GENERATE THE TEST DATA
        cwd = self.problem.tmpdir / 'data' / 'fuzz'
        cwd.mkdir(parents=True, exist_ok=True)
        name = 'testcase'
        infile = cwd / (name + '.in')
        ansfile = cwd / (name + '.ans')

        assert generator.program is not None

        # Pick a random seed.
        seed = random.randint(0, 2**31 - 1)

        command = generator.cache_command(seed=seed)

        bar = ProgressBar(f'Fuzz {i}: {command}', max_len=self.max_submission_len)

        bar.start(f'generate {command}')
        result = generator.run(bar, cwd, name, seed)
        if result.ok is not True:
            bar.finalize()
            return
        bar.done()

        testcase = run.Testcase(self.problem, infile, short_path=Path('fuzz') / (name + '.in'))

        # Validate the manual or generated .in.
        bar.start('validate input')
        if not testcase.validate_format('input_format', bar=bar, constraints=None):
            bar.finalize()
            return
        bar.done()

        # Generate .ans.
        if not self.problem.interactive:
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
        
        bar.start('Run submissions')
        save = False
        def run_submission(submission):
            nonlocal save
            r = run.Run(self.problem, submission, testcase)
            localbar = bar.start(submission)
            result = r.run()
            if result.verdict != 'ACCEPTED':
                save = True
                localbar.error(f'{result.verdict}!')
            localbar.done()

        # Run all submissions against the testcase.
        p = parallel.Parallel(run_submission, pin=True)
        for submission in self.submissions:
            p.put(submission)
        p.done()
        if save:
            bar.log('Saving testcase in generators.yaml.')
            self._save_test(command)
        bar.done()

        bar.global_logged = False
        bar.finalize(print_done=False)
