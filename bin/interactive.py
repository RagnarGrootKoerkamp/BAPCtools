import signal
import time
import subprocess
import sys
import threading

import config

from util import *

if not is_windows():
    import fcntl
    import resource

BUFFER_SIZE = 2**20


# Return a ExecResult object amended with verdict.
def run_interactive_testcase(
    run,
    # False: Return as part of ExecResult
    # None: print to stdout
    validator_error=False,
    team_error=False,
    *,
    # False/None: no output
    # True: stdout
    # else: path
    interaction=False,
    submission_args=None
):

    output_validators = run.problem.validators('output')
    if output_validators is False:
        fatal('No output validators found!')

    assert len(output_validators) == 1
    output_validator = output_validators[0]

    # Set limits
    validator_timeout = config.DEFAULT_INTERACTION_TIMEOUT

    memory_limit = get_memory_limit()
    timelimit = run.problem.settings.timelimit
    timeout = run.problem.settings.timeout

    # Validator command
    validator_command = (
        output_validator.run_command
        + [
            run.testcase.in_path.resolve(),
            run.testcase.ans_path.resolve(),
            run.feedbackdir.resolve(),
        ]
        + run.problem.settings.validator_flags
    )

    submission_command = run.submission.run_command
    if submission_args:
        submission_command += submission_args

    # Both validator and submission run in their own directory.
    validator_dir = output_validator.tmpdir
    submission_dir = run.submission.tmpdir

    if config.args.verbose >= 2:
        print('Validator:  ', *validator_command, file=sys.stderr)
        print('Submission: ', *submission_command, file=sys.stderr)

    # On Windows:
    # - Start the validator
    # - Start the submission
    # - Wait for the submission to complete or timeout
    # - Wait for the validator to complete.
    # This cannot handle cases where the validator reports WA and the submission timeout out
    # afterwards.
    if is_windows() or is_mac():

        if validator_error is False:
            validator_error = subprocess.PIPE
        if team_error is False:
            team_error = subprocess.PIPE

        # Start the validator.
        validator_process = subprocess.Popen(
            validator_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=validator_error,
            cwd=validator_dir,
            bufsize=BUFFER_SIZE,
        )

        # Start and time the submission.
        # TODO: use rusage instead
        tstart = time.monotonic()
        exec_res = exec_command(
            submission_command,
            expect=0,
            stdin=validator_process.stdout,
            stdout=validator_process.stdin,
            stderr=team_error,
            cwd=submission_dir,
            timeout=timeout,
        )

        # Wait
        (validator_out, validator_err) = validator_process.communicate()

        tend = time.monotonic()

        did_timeout = tend - tstart > timelimit

        validator_ok = validator_process.returncode

        print_verdict = None
        if validator_ok != config.RTV_AC and validator_ok != config.RTV_WA:
            config.n_error += 1
            verdict = 'VALIDATOR_CRASH'
        elif did_timeout:
            verdict = 'TIME_LIMIT_EXCEEDED'
            if tend - tstart >= timeout:
                print_verdict = 'TLE (aborted)'
        elif exec_res.ok is not True:
            verdict = 'RUN_TIME_ERROR'
        elif validator_ok == config.RTV_WA:
            verdict = 'WRONG_ANSWER'
        elif validator_ok == config.RTV_AC:
            verdict = 'ACCEPTED'

        if not validator_err:
            validator_err = bytes()

        # Set result.err to validator error and result.out to team error.
        return ExecResult(
            True,
            tend - tstart,
            validator_err.decode('utf-8', 'replace'),
            exec_res.err,
            verdict,
            print_verdict,
        )

    # On Linux:
    # - Create 2 pipes
    # - Update the size to 1MB
    # - Start validator
    # - Start submission, limiting CPU time to timelimit+1s
    # - Set alarm for timelimit+1s, and kill submission on SIGALRM if needed.
    # - Wait for either validator or submission to finish
    # - Close first program + write end of pipe + read end of team output if validator exited first with non-AC.
    # - Close remaining program + write end of pipe
    # - Close remaining read end of pipes

    def mkpipe():
        # TODO: is os.O_CLOEXEC needed here?
        r, w = os.pipe2(os.O_CLOEXEC)
        F_SETPIPE_SZ = 1031
        fcntl.fcntl(w, F_SETPIPE_SZ, BUFFER_SIZE)
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

    # Use manual pipes with a large buffer instead of subprocess.PIPE for validator and team output.
    if validator_error is False:
        validator_error_in, validator_error_out = mkpipe()
    else:
        validator_error_in, validator_error_out = None, validator_error
    if team_error is False:
        team_error_in, team_error_out = mkpipe()
    else:
        team_error_in, team_error_out = None, team_error

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

    validator = subprocess.Popen(
        validator_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        # TODO: Make a flag to pass validator error directly to terminal.
        stderr=validator_error_out,
        cwd=validator_dir,
        preexec_fn=limit_setter(validator_command, validator_timeout, None, 0),
    )
    validator_pid = validator.pid
    # add all programs to the same group (for simiplcity we take the pid of the validator)
    # then we can wait for all program ins the same group
    gid = validator_pid

    if interaction:
        team_tee = subprocess.Popen(
            ['python3', '-c', TEE_CODE, '>'],
            stdin=subprocess.PIPE,
            stdout=validator.stdin,
            stderr=interaction_file,
            preexec_fn=limit_setter(None, None, None, gid),
        )
        team_tee_pid = team_tee.pid
        val_tee = subprocess.Popen(
            ['python3', '-c', TEE_CODE, '<'],
            stdin=validator.stdout,
            stdout=subprocess.PIPE,
            stderr=interaction_file,
            preexec_fn=limit_setter(None, None, None, gid),
        )
        val_tee_pid = val_tee.pid

    submission = subprocess.Popen(
        submission_command,
        stdin=(val_tee if interaction else validator).stdout,
        stdout=(team_tee if interaction else validator).stdin,
        stderr=team_error_out,
        cwd=submission_dir,
        preexec_fn=limit_setter(submission_command, timeout, memory_limit, gid),
    )
    submission_pid = submission.pid

    stop_kill_handler = threading.Event()
    def kill_handler_function():
        if stop_kill_handler.wait(timeout + 1):
            return
        nonlocal submission_time
        submission_time = timeout + 1
        try:
            os.kill(submission_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if validator_timeout > timeout and stop_kill_handler.wait(validator_timeout - timeout):
            return
        os.killpg(gid, signal.SIGKILL)

    kill_handler = threading.Thread(target=kill_handler_function, daemon=True)
    kill_handler.start()

    # Will be filled in the loop below.
    validator_status = None
    submission_status = None
    submission_time = None
    first = None

    # Wait for first to finish
    left = 4 if interaction else 2
    first_done = True
    while left > 0:
        pid, status, rusage = os.wait4(-gid, 0)

        # On abnormal exit (e.g. from calling abort() in an assert), we set status to -1.
        status = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1

        if pid == validator_pid:
            if first is None:
                first = 'validator'
            validator_status = status

            # Close the output stream.
            validator.stdout.close()
            os.close(val_out)
            if interaction:
                val_tee.stdout.close()
                os.close(val_log_out)

            # Kill the team submission and everything else in case we already know it's WA.
            if first_done and validator_status != config.RTV_AC:
                stop_kill_handler.set()
                os.killpg(gid, signal.SIGKILL)
            first_done = False
        elif pid == submission_pid:
            if first is None:
                first = 'submission'
            submission_status = status

            # Close the output stream.
            validator.stdin.close()
            os.close(team_out)
            if interaction:
                team_tee.stdin.close()
                os.close(team_log_out)

            # Possibly already written by the alarm.
            if submission_time is None:
                submission_time = rusage.ru_utime + rusage.ru_stime

            first_done = False
        elif interaction:
            if pid == team_tee_pid or pid == val_tee_pid:
                pass
            else:
                assert False
        else:
            assert False

        left -= 1

    stop_kill_handler.set()

    os.close(val_in)
    if interaction:
        os.close(val_log_in)
    os.close(team_in)
    if interaction:
        os.close(team_log_in)

    did_timeout = submission_time > timelimit
    aborted = submission_time >= timeout

    # If submission timed out: TLE
    # If team exists first with TLE/RTE -> TLE/RTE
    # If team exists first nicely -> validator result
    # If validator exits first with WA -> WA
    # If validator exits first with AC:
    # - team TLE/RTE -> TLE/RTE
    # - more team output -> WA
    # - no more team output -> AC

    print_verdict = None
    if aborted:
        verdict = 'TIME_LIMIT_EXCEEDED'
        print_verdict = 'TLE (aborted)'
    elif validator_status != config.RTV_AC and validator_status != config.RTV_WA:
        config.n_error += 1
        verdict = 'VALIDATOR_CRASH'
    elif first == 'validator':
        # WA has priority because validator reported it first.
        if did_timeout:
            verdict = 'TIME_LIMIT_EXCEEDED'
        elif validator_status == config.RTV_WA:
            verdict = 'WRONG_ANSWER'
        elif submission_status != 0:
            verdict = 'RUN_TIME_ERROR'
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
    if validator_error is False:
        os.close(validator_error_out)
        val_err = os.fdopen(validator_error_in).read()
    elif validator_error is not None:
        val_err = validator.stderr.read().decode('utf-8', 'replace')
    team_err = None
    if team_error is False:
        os.close(team_error_out)
        team_err = os.fdopen(team_error_in).read()
    elif team_error is not None:
        team_err = submission.stderr.read().decode('utf-8', 'replace')

    return ExecResult(True, submission_time, val_err, team_err, verdict, print_verdict)
