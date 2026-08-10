import io
import os
import select
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Sequence
from contextlib import ExitStack, nullcontext, suppress
from pathlib import Path
from typing import IO, Literal, Optional, TYPE_CHECKING

from bapctools import config, validate
from bapctools.util import (
    BAR_TYPE,
    eprint,
    exec_command,
    ExecResult,
    ExecStatus,
    is_windows,
    limit_setter,
    PrintBar,
    remove_path,
)
from bapctools.verdicts import Verdict

if TYPE_CHECKING:
    from bapctools.problem import Problem
    from bapctools.run import Run
    from bapctools.test_case import TestCase


class Connection:
    CHUNK_SIZE = 16 * 1024
    READ_LIMIT = 16 * CHUNK_SIZE
    SOFT_BUFFER_LIMIT = 32 * 1024**2  # might be exceeded by up to READ_LIMIT

    def __init__(
        self,
        prefix: str,
        log: Optional[IO[str]],
        read: Optional[IO[bytes]],
        write: Optional[IO[bytes]],
    ) -> None:
        # we need unbuffered IO
        assert isinstance(read, io.RawIOBase)
        assert isinstance(write, io.RawIOBase)
        os.set_blocking(read.fileno(), False)
        os.set_blocking(write.fileno(), False)

        self.prefix: str = prefix
        self.log: Optional[IO[str]] = log
        self.log_buffer: str = ""
        self.read: io.RawIOBase = read
        self.write: io.RawIOBase = write
        self.allow_propagate_close: bool = False

        self.transmitted: int = 0
        self.buffered: int = 0
        self.buffer: deque[memoryview] = deque()

    def reads(self) -> list[io.RawIOBase]:
        if self.read.closed or self.buffered >= Connection.SOFT_BUFFER_LIMIT:
            return []
        return [self.read]

    def writes(self) -> list[io.RawIOBase]:
        if self.write.closed or not self.buffer:
            return []
        return [self.write]

    def _log(self, data: Optional[bytes] = None) -> None:
        if not self.log:
            return
        if data is None:
            if self.log_buffer:
                print(self.prefix, self.log_buffer, sep="", file=self.log)
            self.log = None
        else:
            lines = data.decode(errors="replace").split("\n")
            lines[0] = self.log_buffer + lines[0]
            self.log_buffer = lines.pop()
            if lines:
                print(self.prefix, f"\n{self.prefix}".join(lines), sep="", file=self.log)

    def _try_propagate_closed(self) -> None:
        if (
            self.read.closed
            and not self.buffer
            and not self.write.closed
            and self.allow_propagate_close
        ):
            self.write.close()
            self.handle_write_closed()

    def handle_read_closed(self) -> None:
        if self.read.closed:
            self._log()
            self._try_propagate_closed()

    def attemp_read(self, limit: int = -1) -> None:
        if self.read.closed:
            return self.handle_read_closed()

        total = 0
        while limit < 0 or total < limit:
            try:
                data = self.read.read(Connection.CHUNK_SIZE)
                if data is None:
                    break
                elif len(data) == 0:
                    self.read.close()
                    self.handle_read_closed()
                    break
                else:
                    self._log(data)
                    total += len(data)
                    if not self.write.closed:
                        self.buffer.append(memoryview(data))
            except BlockingIOError:
                break
            except (BrokenPipeError, OSError, ValueError):
                self.read.close()
                self.handle_read_closed()
                break
        self.buffered += total
        self.transmitted += total

    def handle_write_closed(self) -> None:
        if self.write.closed:
            self.buffer.clear()
            self.buffered = 0

    def attemp_write(self, limit: int = -1) -> None:
        if self.write.closed:
            return self.handle_write_closed()

        total = 0
        while (limit < 0 or total < limit) and self.buffer:
            try:
                data = self.buffer[0]
                n = self.write.write(data)
                if not n:
                    break
                if n < len(data):
                    self.buffer[0] = data[n:]
                    break
                else:
                    self.buffer.popleft()
                total += n
            except BlockingIOError:
                break
            except (BrokenPipeError, OSError, ValueError):
                self.write.close()
                self.handle_write_closed()
                break
        self.buffered -= total
        self._try_propagate_closed()


class Relay(threading.Thread):
    def __init__(
        self,
        log: Optional[IO[str]],
        validator: subprocess.Popen[bytes],
        submission: subprocess.Popen[bytes],
    ) -> None:
        super().__init__(daemon=True)
        self.vs = Connection("<", log, validator.stdout, submission.stdin)
        self.sv = Connection(">", log, submission.stdout, validator.stdin)
        self._wait, self._notify = os.pipe()
        os.set_blocking(self._wait, False)
        os.set_blocking(self._notify, False)

    def run(self) -> None:
        while True:
            read = self.vs.reads() + self.sv.reads()
            write = self.vs.writes() + self.sv.writes()
            if not read and not write:
                break
            try:
                readable, writeable, _ = select.select(read + [self._wait], write, [])
            except (ValueError, OSError):
                # some stream in the select is was broken -> check all
                self.vs.handle_read_closed()
                self.vs.handle_write_closed()
                self.sv.handle_read_closed()
                self.sv.handle_write_closed()
                continue

            if self._wait in readable:
                os.read(self._wait, 4096)
                # we are notified because someone closed something
                self.vs.handle_read_closed()
                self.vs.handle_write_closed()
                self.sv.handle_read_closed()
                self.sv.handle_write_closed()

            for connection in (self.vs, self.sv):
                if connection.read in readable:
                    connection.attemp_read(Connection.READ_LIMIT)
                if connection.write in writeable:
                    connection.attemp_write()

    def notify(self) -> None:
        os.write(self._notify, b"x")

    def close_validator(self) -> None:
        # self.sv.write == validator.stdin
        self.sv.write.close()
        self.vs.allow_propagate_close = True
        self.notify()

    def close_submission(self) -> None:
        # self.vs.write == submission.stdin
        self.vs.write.close()
        self.sv.allow_propagate_close = True
        self.notify()


def _close(pipe: Optional[IO[bytes]]) -> None:
    if pipe:
        pipe.close()


# Return a ExecResult object amended with verdict.
def run_interactive_test_case(
    run: "Run",
    # False: Return as part of ExecResult
    # None: print to stdout
    validator_error: Literal[False] | None = False,
    team_error: Literal[False] | None = False,
    *,
    # False/None: no output
    # True: stderr
    # else: path
    interaction: Optional[bool | Path] = False,
    submission_args: Optional[Sequence[str | Path]] = None,
    bar: BAR_TYPE = PrintBar(),
) -> Optional[ExecResult]:
    output_validators = run.problem.validators(validate.OutputValidator)
    if not output_validators:
        return None
    output_validator = output_validators[0]

    # Set limits
    validation_time = run.problem.limits.validation_time
    validation_memory = run.problem.limits.validation_memory

    time_limit = run.problem.limits.time_limit
    timeout = run.problem.limits.timeout
    memory = run.problem.limits.memory

    # Validator command
    assert output_validator.run_command, "Output validator must be built"
    validator_command = [
        *output_validator.run_command,
        run.in_path.absolute(),
        run.test_case.ans_path.absolute(),
        run.feedbackdir.absolute(),
        *run.test_case.get_test_case_yaml(bar).output_validator_args,
    ]

    # Submission command
    assert run.submission.run_command, "Submission must be built"
    submission_command = run.submission.run_command
    if submission_args:
        submission_command = [*submission_command, *submission_args]

    validator_dir = run.feedbackdir.absolute()
    submission_dir = run.submission.tmpdir

    nextpass = run.feedbackdir / "nextpass.in" if run.problem.multi_pass else None

    if config.args.verbose >= 2:
        eprint("Validator:  ", *validator_command)
        eprint("Submission: ", *submission_command)

    # On Windows:
    # - Start the validator
    # - Start the submission
    # - Wait for the submission to complete or timeout
    # - Wait for the validator to complete.
    # This cannot handle cases where the validator reports WA/RTE and the submission timeout
    # afterwards.
    if is_windows():
        if isinstance(interaction, Path):
            bar.warn("Cannot create .interaction file on windows")

        pass_id = 0
        max_duration = 0.0
        tle_result = None
        while True:
            pass_id += 1
            # Start the validator.
            validator_process = subprocess.Popen(
                validator_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE if validator_error is False else None,
                cwd=validator_dir,
            )

            # Start and time the submission.
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

            timeout_expired = False
            try:
                # Wait
                (validator_out, validator_err) = validator_process.communicate(
                    timeout=validation_time
                )
            except subprocess.TimeoutExpired:
                # Timeout expired.
                timeout_expired = True
                validator_process.kill()
                (validator_out, validator_err) = validator_process.communicate()
            tend = time.monotonic()

            duration = tend - tstart
            if duration >= timeout:
                timeout_expired = True
            elif timeout_expired:
                duration = timeout
            max_duration = max(max_duration, duration)

            validator_status = validator_process.returncode

            if validator_status not in [config.RTV_AC, config.RTV_WA]:
                if timeout_expired:
                    bar.error(f"Validator TIMEOUT after {duration:.1f}s")
                else:
                    config.n_error += 1
                verdict = Verdict.VALIDATOR_CRASH
            elif validator_status == config.RTV_WA and nextpass and nextpass.is_file():
                bar.error("got WRONG_ANSWER but found nextpass.in")
                verdict = Verdict.VALIDATOR_CRASH
            elif duration > time_limit:
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
                validator_err = b""

            if verdict == Verdict.TIME_LIMIT_EXCEEDED:
                if not run._continue_with_tle(verdict, max_duration >= timeout):
                    break
            elif verdict != Verdict.ACCEPTED:
                break

            if not run._prepare_nextpass(nextpass):
                break

            assert run.problem.limits.validation_passes is not None
            if pass_id >= run.problem.limits.validation_passes:
                bar.error("exceeded limit of validation_passes")
                verdict = Verdict.VALIDATOR_CRASH
                break

        run._visualize_output(bar)

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

    # On Posix:
    # - Start validator
    # - Start submission, limiting CPU time to time_limit+1s
    # - Set alarm for time_limit+1s, and kill submission on SIGALRM if needed.
    # - Wait for either validator or submission to finish
    # - Close first program + write end of pipe + read end of team output if validator exited first with non-AC.
    # - Close remaining program + write end of pipe
    # - Close remaining read end of pipes

    if isinstance(interaction, Path):
        assert not interaction.is_relative_to(run.tmpdir)
    elif interaction:
        assert threading.current_thread() is threading.main_thread()

    with (
        interaction.open("a")
        if isinstance(interaction, Path)
        else nullcontext(sys.stderr if interaction else None) as interaction_file  # type: ignore[attr-defined]
    ):
        pass_id = 0
        max_duration = 0
        tle_result = None
        while True:
            pass_id += 1

            # mixing os.wait4 with subprocess.wait is unsafe so we store which
            # PIDs have been reaped by os.wait4
            reaped = []

            def kill_process(process: subprocess.Popen[bytes]) -> None:
                if process.pid not in reaped:
                    with suppress(ProcessLookupError, PermissionError):
                        os.kill(process.pid, signal.SIGKILL)
                        os.waitpid(process.pid, 0)
                        reaped.append(process.pid)
                _close(process.stdin)
                _close(process.stdout)
                _close(process.stderr)

            with ExitStack() as cleanup:
                validator = subprocess.Popen(
                    validator_command,
                    bufsize=0,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    # TODO: Make a flag to pass validator error directly to terminal.
                    stderr=subprocess.PIPE if validator_error is False else None,
                    cwd=validator_dir,
                    preexec_fn=limit_setter(
                        validator_command, validation_time, validation_memory, 0
                    ),
                )
                cleanup.callback(lambda: kill_process(validator))
                # add all programs to the same group (for simplicity we take the pid of the validator)
                # then we can wait for all program ins the same group
                gid = validator.pid

                assert validator.stdin and validator.stdout
                submission = subprocess.Popen(
                    submission_command,
                    bufsize=0,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE if team_error is False else None,
                    cwd=submission_dir,
                    preexec_fn=limit_setter(submission_command, timeout, memory, gid),
                )
                cleanup.callback(lambda: kill_process(submission))

                stop_kill_handler = threading.Event()
                validator_time: Optional[float] = None
                submission_time: Optional[float] = None

                def kill_handler_function() -> None:
                    if stop_kill_handler.wait(timeout + 1):
                        return
                    nonlocal validator_time, submission_time
                    submission_time = timeout + 1
                    with suppress(ProcessLookupError, PermissionError):
                        if submission.pid not in reaped:
                            os.kill(submission.pid, signal.SIGKILL)
                    time_gap = validation_time - timeout + 1
                    if time_gap > 0 and stop_kill_handler.wait(time_gap):
                        return
                    validator_time = validation_time + 1
                    with suppress(ProcessLookupError, PermissionError):
                        os.kill(validator.pid, signal.SIGKILL)

                kill_handler = threading.Thread(target=kill_handler_function, daemon=True)
                kill_handler.start()

                relay = Relay(interaction_file, validator, submission)
                relay.start()

                validator_status = None
                submission_status = None
                first = None
                while validator_status is None or submission_status is None:
                    pid, status, rusage = os.wait4(-gid, 0)
                    reaped.append(pid)

                    # On abnormal exit (e.g. from calling abort() in an assert), we set status to -1.
                    status = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1

                    # -2 corresponds to SIGINT, i.e. keyboard interrupt / CTRL-C.
                    if status == -2:
                        raise KeyboardInterrupt()

                    if pid == validator.pid:
                        if first is None:
                            first = "validator"
                        validator_status = status
                        relay.close_validator()

                        # Possibly already written by the alarm.
                        if validator_time is None:
                            validator_time = rusage.ru_utime + rusage.ru_stime

                        # Kill the team submission and everything else in case we already know it's WA.
                        if submission.pid not in reaped and validator_status != config.RTV_AC:
                            stop_kill_handler.set()
                            with suppress(ProcessLookupError, PermissionError):
                                os.kill(submission.pid, signal.SIGKILL)
                    else:
                        assert pid == submission.pid
                        if first is None:
                            first = "submission"
                        submission_status = status
                        relay.close_submission()

                        # Possibly already written by the alarm.
                        if submission_time is None:
                            submission_time = rusage.ru_utime + rusage.ru_stime

                stop_kill_handler.set()

                relay.notify()
                relay.join()

                if not config.args.no_test_case_sanity_checks:
                    transmission_limit = 10  # in MiB
                    inMiB = 1024**2
                    if relay.vs.transmitted >= transmission_limit * inMiB:
                        bar.warn(f"Validator wrote over {transmission_limit}MiB")
                    if relay.sv.transmitted >= transmission_limit * inMiB:
                        bar.warn(f"Submission wrote over {transmission_limit}MiB")

                assert validator_time is not None
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
                    if validator_time > validation_time:
                        bar.error(f"Validator TIMEOUT after {duration:.1f}s")
                    else:
                        config.n_error += 1
                    verdict = Verdict.VALIDATOR_CRASH
                elif validator_status == config.RTV_WA and nextpass and nextpass.is_file():
                    bar.error("got WRONG_ANSWER but found nextpass.in")
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

            if verdict == Verdict.TIME_LIMIT_EXCEEDED:
                if not run._continue_with_tle(verdict, max_duration >= timeout):
                    break
            elif verdict != Verdict.ACCEPTED:
                break

            if not run._prepare_nextpass(nextpass):
                break

            assert run.problem.limits.validation_passes is not None
            if pass_id >= run.problem.limits.validation_passes:
                bar.error("exceeded limit of validation_passes")
                verdict = Verdict.VALIDATOR_CRASH
                break

            if interaction:
                print("---", file=interaction_file or sys.stderr, flush=True)

    run._visualize_output(bar or PrintBar("Visualize interaction"))

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


def _feedback(run: "Run", err: bytes) -> str:
    judgemessage = run.feedbackdir / "judgemessage.txt"
    judgeerror = run.feedbackdir / "judgeerror.txt"
    res = "" if err is None else err.decode("utf-8", "replace")
    if judgeerror.is_file():
        res = judgeerror.read_text(errors="replace")
    if len(res) == 0 and judgemessage.is_file():
        res = judgemessage.read_text(errors="replace")
    return res


# run the interactor without submission to see if it prints first
def interactor_prints_unprompted(
    problem: "Problem", test_case: "TestCase", wait: float = 0.1
) -> Optional[bool]:
    output_validators = problem.validators(validate.OutputValidator)
    if not output_validators:
        return None
    output_validator = output_validators[0]
    assert output_validator.run_command

    validator_dir = output_validator.tmpdir
    feedbackdir = problem.tmpdir / "tool_runs" / "interaction_feedback"
    remove_path(feedbackdir)
    feedbackdir.mkdir(exist_ok=True, parents=True)

    command = [
        *output_validator.run_command,
        test_case.in_path.absolute(),
        test_case.ans_path.absolute(),
        feedbackdir.absolute(),
        *test_case.get_test_case_yaml(PrintBar("Interaction run")).output_validator_args,
    ]

    validator_process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=validator_dir,
    )
    time.sleep(wait)
    validator_process.kill()
    stdout, _ = validator_process.communicate()
    return bool(stdout)
