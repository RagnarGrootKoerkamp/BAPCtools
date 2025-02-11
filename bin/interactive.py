import signal
import time
import subprocess
import sys
import threading
from typing import Final, Literal, Optional, TYPE_CHECKING

import config
from util import *
import validate
from verdicts import Verdict

if TYPE_CHECKING:
    from run import Run

BUFFER_SIZE: Final = 2**20


# Return a ExecResult object amended with verdict.
def run_interactive_testcase(
    run: "Run",
    # False: Return as part of ExecResult
    # None: print to stdout
    validator_error: Literal[False] | None = False,
    team_error: Literal[False] | None = False,
    *,
    # False/None: no output
    # True: stdout
    # else: path
    interaction: Optional[bool | Path] = False,
    submission_args: Optional[list[str]] = None,
):
    output_validators = run.problem.validators(validate.OutputValidator)
    if len(output_validators) != 1:
        return None
    output_validator = output_validators[0]

    # Set limits
    validation_time = run.problem.limits.validation_time
    validation_memory = run.problem.limits.validation_memory

    time_limit = run.problem.limits.time_limit
    timeout = run.problem.limits.timeout
    memory = run.problem.limits.memory

    # Validator command
    def get_validator_command():
        assert output_validator.run_command, "Output validator must be built"
        return (
            output_validator.run_command
            + [
                run.in_path.resolve(),
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

    nextpass = run.feedbackdir / "nextpass.in" if run.problem.multi_pass else False

    if config.args.verbose >= 2:
        print("Validator:  ", *get_validator_command(), file=sys.stderr)
        print("Submission: ", *submission_command, file=sys.stderr)

    # On Windows:
    # - Start the validator
    # - Start the submission
    # - Wait for the submission to complete or timeout
    # - Wait for the validator to complete.
    # This cannot handle cases where the validator reports WA and the submission timeout out
    # afterwards.
    if is_windows() or is_bsd():
        pass_id = 0
        max_duration = 0.0
        tle_result = None
        while True:
            pass_id += 1
            # Start the validator.
            validator_command = get_validator_command()
            validator_process = subprocess.Popen(
                validator_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE if validator_error is False else None,
                cwd=validator_dir,
            )

            # Start and time the submission.
            # TODO: use rusage instead
            tstart = time.monotonic()
            exec_res = exec_command(
                submission_command,
                stdin=validator_process.stdout,
                stdout=validator_process.stdin,
                stderr=subprocess.PIPE if team_error is False else None,
                cwd=submission_dir,
                timeout=timeout,
                memory=memory,
            )

            # Wait
            (validator_out, validator_err) = validator_process.communicate(timeout=validation_time)

            tend = time.monotonic()
            max_duration = max(max_duration, tend - tstart)

            validator_status = validator_process.returncode

            if validator_status not in [config.RTV_AC, config.RTV_WA]:
                config.n_error += 1
                verdict = Verdict.VALIDATOR_CRASH
            elif validator_status == config.RTV_WA and nextpass and nextpass.is_file():
                error("got WRONG_ANSWER but found nextpass.in")
                verdict = Verdict.VALIDATOR_CRASH
            elif tend - tstart > time_limit:
                verdict = Verdict.TIME_LIMIT_EXCEEDED
                if tle_result is None:
                    # Set result.err to validator error and result.out to team error.
                    tle_result = ExecResult(
                        None,
                        ExecStatus.ACCEPTED,
                        max_duration,
                        max_duration >= timeout,
                        _feedback(run, validator_err),
                        exec_res.err,
                        verdict,
                        pass_id if run.problem.multi_pass else None,
                    )
                else:
                    tle_result.timeout_expired |= max_duration >= timeout
            elif not exec_res.status:
                verdict = Verdict.RUNTIME_ERROR
            elif validator_status == config.RTV_WA:
                verdict = Verdict.WRONG_ANSWER
            elif validator_status == config.RTV_AC:
                verdict = Verdict.ACCEPTED
            else:
                verdict = Verdict.VALIDATOR_CRASH

            if not validator_err:
                validator_err = bytes()

            if not verdict and not run._continue_with_tle(verdict, max_duration >= timeout):
                break

            if not run._prepare_nextpass(nextpass):
                break

            assert run.problem.limits.validation_passes is not None
            if pass_id >= run.problem.limits.validation_passes:
                error("exceeded limit of validation_passes")
                verdict = Verdict.VALIDATOR_CRASH
                break

        if tle_result is None:
            # Set result.err to validator error and result.out to team error.
            return ExecResult(
                None,
                ExecStatus.ACCEPTED,
                max_duration,
                max_duration >= timeout,
                _feedback(run, validator_err),
                exec_res.err,
                verdict,
                pass_id if run.problem.multi_pass else None,
            )
        else:
            tle_result.duration = max_duration
            return tle_result

    # On Linux:
    # - Start validator
    # - Start submission, limiting CPU time to time_limit+1s
    # - Set alarm for time_limit+1s, and kill submission on SIGALRM if needed.
    # - Wait for either validator or submission to finish
    # - Close first program + write end of pipe + read end of team output if validator exited first with non-AC.
    # - Close remaining program + write end of pipe
    # - Close remaining read end of pipes

    interaction_file = None
    # TODO: Print interaction when needed.
    if interaction and interaction is not True:
        assert not interaction.is_relative_to(run.tmpdir)
        interaction_file = interaction.open("a")
        interaction = True

    # Connect pipes with tee.
    TEE_CODE = R"""
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
"""

    pass_id = 0
    max_duration = 0
    tle_result = None
    while True:
        pass_id += 1
        validator_command = get_validator_command()
        validator = subprocess.Popen(
            validator_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # TODO: Make a flag to pass validator error directly to terminal.
            stderr=subprocess.PIPE if validator_error is False else None,
            cwd=validator_dir,
            pipesize=BUFFER_SIZE,
            preexec_fn=limit_setter(validator_command, validation_time, validation_memory, 0),
        )
        validator_pid = validator.pid
        # add all programs to the same group (for simplicity we take the pid of the validator)
        # then we can wait for all program ins the same group
        gid = validator_pid

        assert validator.stdin and validator.stdout

        if interaction:
            team_tee = subprocess.Popen(
                ["python3", "-c", TEE_CODE, ">"],
                stdin=subprocess.PIPE,
                stdout=validator.stdin,
                stderr=interaction_file,
                pipesize=BUFFER_SIZE,
                preexec_fn=limit_setter(None, None, None, gid),
            )
            team_tee_pid = team_tee.pid
            val_tee = subprocess.Popen(
                ["python3", "-c", TEE_CODE, "<"],
                stdin=validator.stdout,
                stdout=subprocess.PIPE,
                stderr=interaction_file,
                pipesize=BUFFER_SIZE,
                preexec_fn=limit_setter(None, None, None, gid),
            )
            val_tee_pid = val_tee.pid

        submission = subprocess.Popen(
            submission_command,
            stdin=(val_tee if interaction else validator).stdout,
            stdout=(team_tee if interaction else validator).stdin,
            stderr=subprocess.PIPE if team_error is False else None,
            cwd=submission_dir,
            pipesize=BUFFER_SIZE,
            preexec_fn=limit_setter(submission_command, timeout, memory, gid),
        )
        submission_pid = submission.pid

        stop_kill_handler = threading.Event()
        submission_time: Optional[float] = None

        def kill_handler_function():
            if stop_kill_handler.wait(timeout + 1):
                return
            nonlocal submission_time
            submission_time = timeout + 1
            try:
                os.kill(submission_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if validation_time > timeout and stop_kill_handler.wait(validation_time - timeout):
                return
            os.killpg(gid, signal.SIGKILL)

        kill_handler = threading.Thread(target=kill_handler_function, daemon=True)
        kill_handler.start()

        # Will be filled in the loop below.
        validator_status = None
        submission_status = None
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
                    first = "validator"
                validator_status = status

                # Close the output stream.
                validator.stdout.close()
                if interaction:
                    assert val_tee.stdout
                    val_tee.stdout.close()

                # Kill the team submission and everything else in case we already know it's WA.
                if first_done and validator_status != config.RTV_AC:
                    stop_kill_handler.set()
                    os.killpg(gid, signal.SIGKILL)
                first_done = False
            elif pid == submission_pid:
                if first is None:
                    first = "submission"
                submission_status = status

                # Close the output stream.
                validator.stdin.close()
                if interaction:
                    assert team_tee.stdin
                    team_tee.stdin.close()

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

        assert submission_time is not None
        did_timeout = submission_time > time_limit
        aborted = submission_time >= timeout
        max_duration = max(max_duration, submission_time)

        # If submission timed out: TLE
        # If team exists first with TLE/RTE -> TLE/RTE
        # If team exists first nicely -> validator result
        # If validator exits first with WA -> WA
        # If validator exits first with AC:
        # - team TLE/RTE -> TLE/RTE
        # - more team output -> WA
        # - no more team output -> AC

        if validator_status not in [config.RTV_AC, config.RTV_WA]:
            config.n_error += 1
            verdict = Verdict.VALIDATOR_CRASH
        elif validator_status == config.RTV_WA and nextpass and nextpass.is_file():
            error("got WRONG_ANSWER but found nextpass.in")
            verdict = Verdict.VALIDATOR_CRASH
        elif aborted:
            verdict = Verdict.TIME_LIMIT_EXCEEDED
        elif first == "validator":
            # WA has priority because validator reported it first.
            if did_timeout:
                verdict = Verdict.TIME_LIMIT_EXCEEDED
            elif validator_status == config.RTV_WA:
                verdict = Verdict.WRONG_ANSWER
            elif submission_status != 0:
                verdict = Verdict.RUNTIME_ERROR
            else:
                verdict = Verdict.ACCEPTED
        else:
            assert first == "submission"
            if submission_status != 0:
                verdict = Verdict.RUNTIME_ERROR
            elif did_timeout:
                verdict = Verdict.TIME_LIMIT_EXCEEDED
            elif validator_status == config.RTV_WA:
                verdict = Verdict.WRONG_ANSWER
            else:
                verdict = Verdict.ACCEPTED

        val_err = None
        if validator_error is False:
            assert validator.stderr
            val_err = _feedback(run, validator.stderr.read())
        team_err = None
        if team_error is False:
            assert submission.stderr
            team_err = submission.stderr.read().decode("utf-8", "replace")

        if verdict == Verdict.TIME_LIMIT_EXCEEDED:
            if tle_result is None:
                tle_result = ExecResult(
                    None,
                    ExecStatus.ACCEPTED,
                    max_duration,
                    aborted,
                    val_err,
                    team_err,
                    verdict,
                    pass_id if run.problem.multi_pass else None,
                )
            else:
                tle_result.timeout_expired |= aborted

        if not verdict and not run._continue_with_tle(verdict, aborted):
            break

        if not run._prepare_nextpass(nextpass):
            break

        assert run.problem.limits.validation_passes is not None
        if pass_id >= run.problem.limits.validation_passes:
            error("exceeded limit of validation_passes")
            verdict = Verdict.VALIDATOR_CRASH
            break

        if interaction:
            print("---", file=sys.stderr if interaction is None else interaction_file, flush=True)

    if interaction_file is not None:
        interaction_file.close()

    if tle_result is None:
        return ExecResult(
            None,
            ExecStatus.ACCEPTED,
            max_duration,
            aborted,
            val_err,
            team_err,
            verdict,
            pass_id if run.problem.multi_pass else None,
        )
    else:
        tle_result.duration = max_duration
        return tle_result


def _feedback(run, err):
    judgemessage = run.feedbackdir / "judgemessage.txt"
    judgeerror = run.feedbackdir / "judgeerror.txt"
    if err is None:
        err = ""
    else:
        err = err.decode("utf-8", "replace")
    if judgeerror.is_file():
        err = judgeerror.read_text(errors="replace")
    if len(err) == 0 and judgemessage.is_file():
        err = judgemessage.read_text(errors="replace")
    return err
