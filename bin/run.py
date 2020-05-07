import signal
import time
import subprocess

import build
import config
import validate

from util import *

if not is_windows():
    import fcntl
    import resource


def _get_submission_type(s):
    ls = str(s).lower()
    if 'wrong_answer' in ls:
        return 'WRONG_ANSWER'
    if 'time_limit_exceeded' in ls:
        return 'TIME_LIMIT_EXCEEDED'
    if 'run_time_error' in ls:
        return 'RUN_TIME_ERROR'
    return 'ACCEPTED'


# returns a map {answer type -> [(name, command)]}
def _get_submissions(problem):
    programs = []

    if hasattr(config.args, 'submissions') and config.args.submissions:
        for submission in config.args.submissions:
            if Path(problem / submission).parent == problem / 'submissions':
                programs += glob(problem / submission, '*')
            else:
                programs.append(problem / submission)
    else:
        for verdict in config.PROBLEM_OUTCOMES:
            programs += glob(problem, f'submissions/{verdict.lower()}/*')

    if len(programs) == 0:
        error('No submissions found!')

    run_commands = build.build_programs(programs, True)
    submissions = {
        'ACCEPTED': [],
        'WRONG_ANSWER': [],
        'TIME_LIMIT_EXCEEDED': [],
        'RUN_TIME_ERROR': []
    }
    for c in run_commands:
        submissions[_get_submission_type(c[0])].append(c)

    return submissions

# TODO: Reuse Submission(Invocation) object.
# TODO: Use new Testcase object.
# TODO: Introduce new Run object containing a submission and testcase
# TODO: Parallelize running Runs.



class Run:
    def __init__(self, submission, testcase):
        pass

# Return (ret, duration, err, out)
def run_testcase(run_command, testcase, outfile, timeout, crop=True):
    with testcase.in_path.open('rb') as inf:

        def run(outfile):
            did_timeout = False
            tstart = time.monotonic()
            if outfile is None:
                # Print both stdout and stderr directly to the terminal.
                ok, err, out = exec_command(run_command,
                                            expect=0,
                                            crop=crop,
                                            stdin=inf,
                                            stdout=None,
                                            stderr=None,
                                            timeout=timeout)
            else:
                ok, err, out = exec_command(run_command,
                                            expect=0,
                                            crop=crop,
                                            stdin=inf,
                                            stdout=outfile,
                                            timeout=timeout)
            tend = time.monotonic()

            return ok, tend - tstart, err, out

        if outfile is None:
            return run(outfile)
        else:
            return run(outfile.open('wb'))


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


# return (verdict, time, remark)
def _process_testcase(run_command, testcase, outfile, settings, output_validators):

    if 'interactive' in settings.validation:
        return process_interactive_testcase(run_command, testcase, settings, output_validators)

    timelimit, timeout = get_time_limits(settings)
    ok, duration, err, out = run_testcase(run_command, testcase, outfile, timeout)
    did_timeout = duration > timelimit
    verdict = None
    if did_timeout:
        verdict = 'TIME_LIMIT_EXCEEDED'
    elif ok is not True:
        verdict = 'RUN_TIME_ERROR'
        err = 'Exited with code ' + str(ok) + ':\n' + err
    else:
        assert settings.validation in ['default', 'custom']
        if settings.validation == 'default':
            ok, err, out = validate.default_output_validator(testcase.ans_path, outfile,
                                                             settings)
        elif settings.validation == 'custom':
            ok, err, out = validate.custom_output_validator(testcase, outfile, settings,
                                                            output_validators)

        if ok is True:
            verdict = 'ACCEPTED'
        elif ok is False:
            verdict = 'WRONG_ANSWER'
        else:
            config.n_error += 1
            verdict = 'VALIDATOR_CRASH'

    return (verdict, duration, err, out)


# TODO: Start using the Submission(Invocation) class from Generate here.
# program is of the form (name, command)
# return outcome
# always: failed submissions
# -v: all programs and their results (+failed testcases when expected is 'accepted')
def _run_submission(problem, submission,
                    testcases,
                    settings,
                    output_validators,
                    max_submission_len,
                    expected='ACCEPTED',
                    table_dict=None):
    time_total = 0
    time_max = 0
    testcase_max_time = None

    action = 'Running ' + str(submission[0])
    max_total_length = max(max([len(t.name) for t in testcases]), 15) + max_submission_len
    max_testcase_len = max_total_length - len(str(submission[0]))

    printed = False
    bar = ProgressBar(action, max_testcase_len, len(testcases))

    # TODO: Run multiple testcases in parallel.
    final_verdict = 'ACCEPTED'
    for testcase in testcases:
        bar.start(testcase.name)
        # TODO: test.out should really depend on the testcase and maybe the submission as well.
        # This is especially needed when running multiple cases/submissions in parallel.
        outfile = config.tmpdir / problem.name / 'runs' / submission[0] / testcase.short_path.with_suffix('.out')
        outfile.parent.mkdir(exist_ok=True, parents=True)
        verdict, runtime, err, out = _process_testcase(submission[1], testcase, outfile, settings,
                                                       output_validators)

        if config.PRIORITY[verdict] > config.PRIORITY[final_verdict]:
            final_verdict = verdict

        # Manage timings, table data, and print output
        time_total += runtime
        if runtime > time_max:
            time_max = runtime
            testcase_max_time = testcase.name

        if table_dict is not None:
            table_dict[testcase.name] = verdict == 'ACCEPTED'

        got_expected = verdict == 'ACCEPTED' or verdict == expected
        color = cc.green if got_expected else cc.red
        print_message = config.verbose > 0 or (not got_expected
                                               and verdict != 'TIME_LIMIT_EXCEEDED')
        message = '{:6.3f}s '.format(runtime) + color + verdict + cc.reset

        # Print stderr whenever something is printed
        if err:
            prefix = '  '
            if err.count('\n') > 1:
                prefix = '\n'
            message += prefix + cc.orange + strip_newline(err) + cc.reset

        # Print stdout when -e is set.
        if out and (verdict == 'VALIDATOR_CRASH' or config.args.error):
            prefix = '  '
            if out.count('\n') > 1:
                prefix = '\n'
            output_type = 'STDOUT'
            if 'interactive' in settings.validation: output_type = 'PROGRAM STDERR'
            message += f'\n{cc.red}{output_type}{cc.reset}' + prefix + cc.orange + strip_newline(
                out) + cc.reset

        if print_message:
            bar.log(message)
            printed = True

        bar.done()

        if not config.verbose and verdict in config.MAX_PRIORITY_VERDICT:
            break

    # Use a bold summary line if things were printed before.
    if printed:
        color = cc.boldgreen if final_verdict == expected else cc.boldred
    else:
        color = cc.green if final_verdict == expected else cc.red

    time_avg = time_total / len(testcases)

    # Print summary line
    boldcolor = cc.bold if printed else ''
    print(
        f'{action:<{max_total_length-6}} {boldcolor}max/avg {time_max:6.3f}s {time_avg:6.3f}s {color}{final_verdict:<20}{cc.reset} @ {testcase_max_time}'
    )

    if config.verbose:
        print()

    return final_verdict == expected


# return true if all submissions for this problem pass the tests
def run_submissions(problem, settings):
    needans = True
    if 'interactive' in settings.validation: needans = False
    testcases = problem.testcases(needans=needans)

    if len(testcases) == 0:
        return False

    output_validators = None
    if settings.validation in ['custom', 'custom interactive']:
        output_validators = validate.get_validators(problem.path, 'output')
        if len(output_validators) == 0:
            error(f'No output validators found, but validation type is: {settings.validation}.')
            return False

    submissions = _get_submissions(problem.path)

    max_submission_len = max([0] +
                             [len(str(x[0])) for cat in submissions for x in submissions[cat]])

    success = True
    verdict_table = []
    for verdict in submissions:
        for submission in submissions[verdict]:
            verdict_table.append(dict())
            success &= _run_submission(problem.path, submission,
                                       testcases,
                                       settings,
                                       output_validators,
                                       max_submission_len,
                                       verdict,
                                       table_dict=verdict_table[-1])

    if hasattr(settings, 'table') and settings.table:
        # Begin by aggregating bitstrings for all testcases, and find bitstrings occurring often (>=config.TABLE_THRESHOLD).
        def single_verdict(row, testcase):
            if testcase in row:
                if row[testcase.name]:
                    return cc.green + '1' + cc.reset
                else:
                    return cc.red + '0' + cc.reset
            else:
                return '-'

        make_verdict = lambda tc: ''.join(map(lambda row: single_verdict(row, tc), verdict_table))
        resultant_count, resultant_id = dict(), dict()
        special_id = 0
        for testcase in testcases:
            resultant = make_verdict(testcase)
            if resultant not in resultant_count:
                resultant_count[resultant] = 0
            resultant_count[resultant] += 1
            if resultant_count[resultant] == config.TABLE_THRESHOLD:
                special_id += 1
                resultant_id[resultant] = special_id

        scores = {}
        for t in testcases:
            scores[t] = 0
        for dct in verdict_table:
            failures = 0
            for t in dct:
                if not dct[t]:
                    failures += 1
            for t in dct:
                if not dct[t]:
                    scores[t] += 1. / failures
        scores_list = sorted(scores.values())

        print('\nVerdict analysis table. Submissions are ordered as above. Higher '
              'scores indicate they are critical to break some submissions.')
        for testcase in testcases:
            # Skip all AC testcases
            if all(map(lambda row: row[testcase.name], verdict_table)): continue

            color = cc.reset
            if len(scores_list) > 6 and scores[testcase.name] >= scores_list[-6]:
                color = cc.orange
            if len(scores_list) > 3 and scores[testcase.name] >= scores_list[-3]:
                color = cc.red
            print(f'{str(testcase.name):<60}', end=' ')
            resultant = make_verdict(testcase)
            print(resultant, end='  ')
            print(f'{color}{scores[testcase.name]:0.3f}{cc.reset}  ', end='')
            if resultant in resultant_id:
                print(str.format('(Type {})', resultant_id[resultant]), end='')
            print(end='\n')

    return success


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
