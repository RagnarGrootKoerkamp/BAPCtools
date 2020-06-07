import signal
import time
import subprocess

import program
import config
import validate

from util import *

if not is_windows():
    import fcntl
    import resource

class Testcase:
    def __init__(self, problem, path):
        assert path.suffix == '.in'

        self.in_path = path
        self.ans_path = path.with_suffix('.ans')
        # Note: Only testcases in problem/data are supported currently.
        self.short_path = path.relative_to(problem.path / 'data')

        # Display name: everything after data/.
        self.name = str(self.short_path.with_suffix(''))

        self.bad = self.short_path.parts[0] == 'bad'

    def with_suffix(self, ext):
        return self.in_path.with_suffix(ext)


# Note: Validators are currently taken from the problem. All validators are run for all testcases.
class Run:
    def __init__(self, problem, submission, testcase):
        self.problem = problem
        self.submission = submission
        self.testcase = testcase
        self.name = self.testcase.name
        self.result = None

    # Return a ExecResult object amended with verdict.
    def run(self):
        tmp_path = config.tmpdir / self.problem.name / 'runs' / self.submission.short_path / self.testcase.short_path
        self.out_path = tmp_path.with_suffix('.out')
        self.feedbackdir = tmp_path.with_suffix('.feedbackdir')
        self.feedbackdir.mkdir(exist_ok=True, parents=True)

        if self.problem.settings.validation == 'custom interactive':
            # TODO
            verdict, duration, err, out =  process_interactive_testcase(run_command, testcase, settings, output_validators)
        else:
            result = self.submission.run(self.testcase.in_path, self.out_path)
            if result.duration > self.problem.settings.timelimit:
                result.verdict = 'TIME_LIMIT_EXCEEDED'
            elif result.ok is not True:
                result.verdict = 'RUN_TIME_ERROR'
                result.err = 'Exited with code ' + str(ok) + ':\n' + result.err
            else:
                if self.problem.settings.validation == 'default':
                    # TODO: Update validators
                    ok, err, out = validate.default_output_validator(self.testcase.ans_path, self.out_path,
                                                                     self.problem.settings)
                elif self.problem.settings.validation == 'custom':
                    # TODO: Update validators
                    ok, err, out = validate.custom_output_validator(self.testcase.ans_path, self.out_path, problme.settings,
                                                                    self.problem.validators('output'))
                result.ok = ok
                result.err = err
                result.out = out

                if result.ok is True:
                    result.verdict = 'ACCEPTED'
                elif result.ok is False:
                    result.verdict = 'WRONG_ANSWER'
                else:
                    config.n_error += 1
                    result.verdict = 'VALIDATOR_CRASH'

        self.result = result
        return result



class Submission(program.Program):
    subdir = 'submissions'
    def __init__(self, problem, path):
        super().__init__(problem, path)

        subdir = self.short_path.parts[0]
        self.expected_verdict = subdir.upper() if subdir.upper() in config.VERDICTS else None
        self.verdict = None
        self.duration = None

    # Run submission on in_path, writing stdout to out_path or stdout if out_path is None.
    # args is used by SubmissionInvocation to pass on additional arguments.
    # Returns ExecResult
    def run(self, in_path, out_path, crop=True, args=[], cwd=None):
        assert self.run_command is not None
        # Just for safety reasons, change the cwd.
        if cwd is None: cwd = out_path.parent
        with in_path.open('rb') as inf:
            out_file = out_path.open('wb') if out_path else None

            # Print stderr to terminal is stdout is None, otherwise return its value.
            result = exec_command_2(self.run_command + args,
                                            crop=crop,
                                            stdin=inf,
                                            stdout=out_file,
                                            stderr=None if out_file is None else True,
                                            timeout=self.problem.settings.timeout,
                                            cwd=cwd)
            if out_file: out_file.close()
            return result

    # Run this submission on all testcases for the current problem.
    # Returns the final verdict.
    def run_all_testcases(self, max_submission_name_len=None, table_dict=None):
        runs = [Run(self.problem, self, testcase) for testcase in self.problem.testcases()]
        bar = ProgressBar('Running ' + self.name, items=runs)

        max_duration = (0, None) # duration, Run
        verdict = (config.PRIORITY['ACCEPTED'], 'ACCEPTED', 0, None) # priority, verdict, duration, Run

        # TODO: Run multiple runs in parallel.
        for run in runs:
            bar.start(run)
            result = run.run()

            verdict = max(verdict, (config.PRIORITY[result.verdict], result.verdict, result.duration, run))
            max_duration = max(max_duration, (result.duration, run))

            if table_dict is not None:
                table_dict[run.name] = result.verdict == 'ACCEPTED'

            got_expected = result.verdict == 'ACCEPTED' or result.verdict == self.expected_verdict

            # Print stderr whenever something is printed
            if result.out and result.err:
                output_type = 'PROGRAM STDERR' if self.problem.settings.validation == 'custom interactive' else 'STDOUT'
                data = f'STDERR:' + util.ProgresBar._format_data(result.err) + '\n{output_type}:' + util.ProgressBar._format_data(result.out) + '\n'
            else:
                data = result.err

            bar.done(got_expected, f'{result.duration:6.3f}s {result.verdict}', data)

            # Lazy judging: stop on the first error when not in verbose mode.
            if not config.verbose and result.verdict in config.MAX_PRIORITY_VERDICT:
                bar.count = None
                break

        self.verdict = verdict[1]
        self.duration = max_duration[0]

        # Use a bold summary line if things were printed before.
        if bar.logged:
            color = cc.boldgreen if self.verdict == self.expected_verdict else cc.boldred
            boldcolor = cc.bold
        else:
            color = cc.green if self.verdict == self.expected_verdict else cc.red
            boldcolor = ''

        bar.finalize(message=f'{max_duration[0]:6.3f}s {color}{verdict[1]:<20}{cc.reset} @ {verdict[3].name}')

        if config.verbose:
            print()

        return self.verdict == self.expected_verdict




# return (verdict, time, validator error, submission error)
def process_interactive_testcase(
        run_command,
        testcase,
        settings,
        output_validators,
        validator_error=False,
        team_error=False,
        *,
        # False/None: no output
        # True: stdout
        # else: path
        interaction=False):
    assert len(output_validators) == 1
    output_validator = output_validators[0]

    # Set limits
    validator_timeout = 60

    memory_limit = get_memory_limit()
    time_limit, timeout = get_time_limits(settings)

    # Validator command
    flags = []
    if settings.space_change_sensitive: flags += ['space_change_sensitive']
    if settings.case_sensitive: flags += ['case_sensitive']
    judgepath = config.tmpdir / 'judge'
    judgepath.mkdir(parents=True, exist_ok=True)
    validator_command = output_validator[1] + [
        testcase.in_path,
        testcase.ans_path, judgepath
    ] + flags

    if validator_error is False: validator_error = subprocess.PIPE
    if team_error is False: team_error = subprocess.PIPE

    # On Windows:
    # - Start the validator
    # - Start the submission
    # - Wait for the submission to complete or timeout
    # - Wait for the validator to complete.
    # This cannot handle cases where the validator reports WA and the submission timeout out
    # afterwards.
    if is_windows():

        # Start the validator.
        validator_process = subprocess.Popen(validator_command,
                                             stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE,
                                             stderr=validator_error,
                                             bufsize=2**20)

        # Start and time the submission.
        # TODO: use rusage instead
        tstart = time.monotonic()
        ok, err, out = exec_command(run_command,
                                    expect=0,
                                    stdin=validator_process.stdout,
                                    stdout=validator_process.stdin,
                                    stderr=team_error,
                                    timeout=timeout)

        # Wait
        (validator_out, validator_err) = validator_process.communicate()

        tend = time.monotonic()

        did_timeout = tend - tstart > time_limit

        validator_ok = validator_process.returncode

        if validator_ok != config.RTV_AC and validator_ok != config.RTV_WA:
            config.n_error += 1
            verdict = 'VALIDATOR_CRASH'
        elif did_timeout:
            verdict = 'TIME_LIMIT_EXCEEDED'
        elif ok is not True:
            verdict = 'RUN_TIME_ERROR'
        elif validator_ok == config.RTV_WA:
            verdict = 'WRONG_ANSWER'
        elif validator_ok == config.RTV_AC:
            verdict = 'ACCEPTED'
        return (verdict, tend - tstart, validator_err.decode('utf-8'), err)

    # On Linux:
    # - Create 2 pipes
    # - Update the size to 1MB
    # - Start validator
    # - Start submission, limiting CPU time to timelimit+1s
    # - Close unused read end of pipes
    # - Set alarm for timelimit+1s, and kill submission on SIGALRM if needed.
    # - Wait for either validator or submission to finish
    # - Close first program + write end of pipe
    # - Close remaining program + write end of pipe

    def mkpipe():
        # TODO: is os.O_CLOEXEC needed here?
        r, w = os.pipe2(os.O_CLOEXEC)
        F_SETPIPE_SZ = 1031
        fcntl.fcntl(w, F_SETPIPE_SZ, 2**20)
        return r, w

    interaction_file = None
    # TODO: Print interaction when needed.
    if interaction:
        interaction_file = None if interaction is True else interaction.open('a')
        interaction = True

    team_log_in, team_out = mkpipe()
    val_log_in, val_out = mkpipe()
    if interaction:
        val_in, team_log_out = mkpipe()
        team_in, val_log_out = mkpipe()
    else:
        val_in = team_log_in
        team_in = val_log_in

    if interaction:
        # Connect pipes with tee.
        TEE_CODE = R'''
import sys
c = sys.argv[1]
new = True
while True:
    l = sys.stdin.read(1)
    if l=='': break
    sys.stdout.write(l)
    sys.stdout.flush()
    if new: sys.stderr.write(c)
    sys.stderr.write(l)
    sys.stderr.flush()
    new = l=='\n'
'''
        team_tee = subprocess.Popen(['python3', '-c', TEE_CODE, '>'],
                                    stdin=team_log_in,
                                    stdout=team_log_out,
                                    stderr=interaction_file)
        team_tee_pid = team_tee.pid
        val_tee = subprocess.Popen(['python3', '-c', TEE_CODE, '<'],
                                   stdin=val_log_in,
                                   stdout=val_log_out,
                                   stderr=interaction_file)
        val_tee_pid = val_tee.pid

    # Run Validator
    def set_validator_limits():
        resource.setrlimit(resource.RLIMIT_CPU, (validator_timeout, validator_timeout))
        # Increase the max stack size from default to the max available.
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_STACK,
                               (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

    validator = subprocess.Popen(validator_command,
                                 stdin=val_in,
                                 stdout=val_out,
                                 stderr=validator_error,
                                 preexec_fn=set_validator_limits)
    validator_pid = validator.pid

    # Run Submission
    def set_submission_limits():
        resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
        # Increase the max stack size from default to the max available.
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_STACK,
                               (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
        if memory_limit:
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

    submission = subprocess.Popen(run_command,
                                  stdin=team_in,
                                  stdout=team_out,
                                  stderr=team_error,
                                  preexec_fn=set_submission_limits)
    submission_pid = submission.pid

    os.close(team_out)
    os.close(val_out)
    if interaction:
        os.close(team_log_out)
        os.close(val_log_out)

    # To be filled
    validator_status = None
    submission_status = None
    submission_time = None
    first = None

    # Raise alarm after timeout reached
    signal.alarm(timeout)

    def kill_submission(signal, frame):
        submission.kill()
        nonlocal submission_time
        submission_time = timeout

    signal.signal(signal.SIGALRM, kill_submission)

    # Wait for first to finish
    for i in range(4 if interaction else 2):
        pid, status, rusage = os.wait3(0)
        status >>= 8

        if pid == validator_pid:
            if first is None: first = 'validator'
            validator_status = status
            # Kill the team submission in case we already know it's WA.
            if i == 0 and validator_status != config.RTV_AC:
                submission.kill()
            continue

        if pid == submission_pid:
            signal.alarm(0)
            if first is None: first = 'submission'
            submission_status = status
            # Possibly already written by the alarm.
            if not submission_time:
                submission_time = rusage.ru_utime + rusage.ru_stime
            continue

        if pid == team_tee_pid: continue
        if pid == val_tee_pid: continue

        assert False

    os.close(team_in)
    os.close(val_in)
    if interaction:
        os.close(team_log_in)
        os.close(val_log_in)

    did_timeout = submission_time > time_limit

    # If team exists first with TLE/RTE -> TLE/RTE
    # If team exists first nicely -> validator result
    # If validator exits first with WA -> WA
    # If validator exits first with AC:
    # - team TLE/RTE -> TLE/RTE
    # - more team output -> WA
    # - no more team output -> AC

    if validator_status != config.RTV_AC and validator_status != config.RTV_WA:
        config.n_error += 1
        verdict = 'VALIDATOR_CRASH'
    elif first == 'validator':
        # WA has priority because validator reported it first.
        if validator_status == config.RTV_WA:
            verdict = 'WRONG_ANSWER'
        elif submission_status != 0:
            verdict = 'RUN_TIME_ERROR'
        elif did_timeout:
            verdict = 'TIME_LIMIT_EXCEEDED'
        else:
            verdict = 'ACCEPTED'
    else:
        assert first == 'submission'
        if submission_status != 0:
            verdict = 'RUN_TIME_ERROR'
        elif did_timeout:
            verdict = 'TIME_LIMIT_EXCEEDED'
        elif validator_status == config.RTV_WA:
            verdict = 'WRONG_ANSWER'
        else:
            verdict = 'ACCEPTED'

    val_err = None
    if validator_error is not None: val_err = validator.stderr.read().decode('utf-8')
    team_err = None
    if team_error is not None: team_err = submission.stderr.read().decode('utf-8')
    return (verdict, submission_time, val_err, team_err)





# TODO: Migrate these TEST subcommands into submission as well.
# TODO: Figure out what exactly to do with this. It's somewhat messy.
def _test_submission(problem, submission, testcases, settings):
    print(ProgressBar.action('Running', str(submission[0])))

    if 'interactive' in settings.validation:
        output_validators = validate.get_validators(problem, 'output')
        if len(output_validators) != 1:
            error(
                'Interactive problems need exactly one output validator. Found {len(output_validators)}.'
            )
            return False

    time_limit, timeout = get_time_limits(settings)
    for testcase in testcases:
        header = ProgressBar.action('Running ' + str(submission[0]), testcase.name)
        print(header)

        if 'interactive' not in settings.validation:
            # err and out should be None because they go to the terminal.
            ok, duration, err, out = run_testcase(submission[1],
                                                  testcase,
                                                  outfile=None,
                                                  timeout=timeout,
                                                  crop=False)
            did_timeout = duration > time_limit
            assert err is None and out is None
            if ok is not True:
                config.n_error += 1
                print(
                    f'{cc.red}Run time error!{cc.reset} exit code {ok} {cc.bold}{duration:6.3f}s{cc.reset}'
                )
            elif did_timeout:
                config.n_error += 1
                print(f'{cc.red}Aborted!{cc.reset} {cc.bold}{duration:6.3f}s{cc.reset}')
            else:
                print(f'{cc.green}Done:{cc.reset} {cc.bold}{duration:6.3f}s{cc.reset}')
            print()

        else:
            # Interactive problem.
            verdict, duration, val_err, team_err = process_interactive_testcase(
                submission[1],
                testcase,
                settings,
                output_validators,
                interaction=True,
                validator_error=None,
                team_error=None)
            if verdict != 'ACCEPTED':
                config.n_error += 1
                print(f'{cc.red}{verdict}{cc.reset} {cc.bold}{duration:6.3f}s{cc.reset}')
            else:
                print(f'{cc.green}{verdict}{cc.reset} {cc.bold}{duration:6.3f}s{cc.reset}')


# Takes a list of submissions and runs them against the chosen testcases.
# Instead of validating the output, this function just prints all output to the
# terminal.
# Note: The CLI only accepts one submission.
def test_submissions(problem, settings):
    testcases = problem.testcases(needans=False)

    if len(testcases) == 0:
        warn('No testcases found!')
        return False

    submissions = _get_submissions(problem.path)

    verdict_table = []
    for verdict in submissions:
        for submission in submissions[verdict]:
            _test_submission(problem.path, submission, testcases, settings)
    return True
