import io
import itertools
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
from queue import SimpleQueue
from typing import Final, IO, Literal, Optional, TYPE_CHECKING

from colorama import Fore, Style

from bapctools import config
from bapctools.util import (
    BAR_TYPE,
    ExecResult,
    ExecStatus,
    is_windows,
    limit_setter,
    PrintBar,
    remove_path,
)
from bapctools.validate import OutputValidator
from bapctools.verdicts import Verdict

if TYPE_CHECKING:
    from bapctools.problem import Problem
    from bapctools.run import Run
    from bapctools.test_case import TestCase


class Connection:
    READ_LIMIT: Final[int] = 256 * 1024
    SOFT_BUFFER_LIMIT: Final[int] = 32 * 1024**2  # might be exceeded by up to READ_LIMIT

    def __init__(
        self,
        prefix: str,
        log: Optional[IO[str]],
        read: Optional[IO[bytes]],
        write: Optional[IO[bytes]],
        *,
        propagate_eof: bool = False,
    ) -> None:
        # we need unbuffered IO
        assert isinstance(read, io.RawIOBase)
        assert isinstance(write, io.RawIOBase)
        os.set_blocking(read.fileno(), False)
        os.set_blocking(write.fileno(), False)

        self.prefix: str = prefix
        self.log: Optional[IO[str]] = log
        self.log_buffer: list[str] = []
        self.read: io.RawIOBase = read
        self.write: io.RawIOBase = write
        self.propagate_eof: bool = propagate_eof

        self.transmitted: int = 0
        self.buffered: int = 0
        self.buffer: deque[memoryview] = deque()
        self.joined: bool = False

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
                print(self.prefix, *self.log_buffer, sep="", file=self.log, flush=True)
                self.log_buffer.clear()
            self.log = None
        else:
            first, *remainig = data.decode(errors="replace").split("\n")
            self.log_buffer.append(first)
            if remainig:
                *complete, incomplete = "".join(self.log_buffer), *remainig
                print(
                    self.prefix,
                    f"\n{self.prefix}".join(complete),
                    sep="",
                    file=self.log,
                    flush=False,
                )
                self.log_buffer = [incomplete] if incomplete else []

    def _try_propagate_eof(self) -> None:
        if self.read.closed and not self.buffer and not self.write.closed and self.propagate_eof:
            self.write.close()
            self.handle_write_closed()

    def handle_read_closed(self) -> None:
        if self.read.closed:
            self._log()
            self._try_propagate_eof()

    def attemp_read(self) -> None:
        if self.read.closed:
            return self.handle_read_closed()

        try:
            data = self.read.read(Connection.READ_LIMIT)
            if data is None:
                pass
            elif len(data) == 0:
                self.read.close()
                self.handle_read_closed()
            else:
                self._log(data)
                self.buffered += len(data)
                self.transmitted += len(data)
                if not self.write.closed:
                    self.buffer.append(memoryview(data))
        except BlockingIOError:
            pass
        except (BrokenPipeError, OSError, ValueError):
            self.read.close()
            self.handle_read_closed()

    def handle_write_closed(self) -> None:
        if self.write.closed:
            self.buffer.clear()
            self.buffered = 0
            self.joined = False

    def attemp_write(self) -> None:
        if self.write.closed:
            return self.handle_write_closed()

        while self.buffer:
            try:
                # This tries to reduce the number of self.write.write calls by joining small buffers
                # Note: Joining is linear, but we have no guarantee on the number of bytes we will
                #       actually write => always joining can lead to O(n^2) behaviour!
                # The current code ensures O(n) worst-case behaviour while still limiting the number
                # of self.write.write calls to 2 (per attemp_write invocation)
                if len(self.buffer) > 1:
                    if not self.joined or self.buffered >= len(self.buffer[0]):
                        data = memoryview(b"".join(self.buffer))
                        self.buffer.clear()
                        self.buffer.append(data)
                        self.joined = True

                data = self.buffer[0]
                n = self.write.write(data)
                if not n:
                    break
                self.buffered -= n
                if n < len(data):
                    self.buffer[0] = data[n:]
                    break
                else:
                    self.buffer.popleft()
                    self.joined = False
            except BlockingIOError:
                break
            except (BrokenPipeError, OSError, ValueError):
                self.write.close()
                self.handle_write_closed()
                break
        self._try_propagate_eof()


class Relay(threading.Thread):
    def __init__(
        self,
        log: Optional[IO[str]],
        validator: subprocess.Popen[bytes],
        submission: subprocess.Popen[bytes],
    ) -> None:
        super().__init__(daemon=True)
        # Domjudge propagates EOF, while Kattis does not
        # https://github.com/DOMjudge/domjudge/pull/1709
        # https://github.com/Kattis/problemtools/blob/b89cb38a65c500928303da19f24ba0f9975662e4/support/interactive/interactive.cc#L257
        # We assume that the output validator knows what it does and directly propagate
        # a closed stream. For the submission on the other hand we only propagte a closed
        # stream after the submission died
        vs, sv = "<>"
        if log is not None and log.isatty():
            vs = f"{Fore.YELLOW}{vs}{Style.RESET_ALL}"
            sv = f"{Fore.CYAN}{sv}{Style.RESET_ALL}"
        self.vs = Connection(vs, log, validator.stdout, submission.stdin, propagate_eof=True)
        self.sv = Connection(sv, log, submission.stdout, validator.stdin)
        self._wait, self._notify = os.pipe()
        os.set_blocking(self._wait, False)
        os.set_blocking(self._notify, False)
        self.first_exception: Optional[KeyboardInterrupt | Exception] = None
        self.switches = 0
        self._last = (False, False)

    def run(self) -> None:
        try:
            exit = False
            while True:
                read = self.vs.reads() + self.sv.reads()
                write = self.vs.writes() + self.sv.writes()
                if exit and not read and not write:
                    break
                try:
                    readable, writeable, _ = select.select(read + [self._wait], write, [])
                except (ValueError, OSError):
                    # some stream in the select is/was broken -> check all
                    self.vs.handle_read_closed()
                    self.vs.handle_write_closed()
                    self.sv.handle_read_closed()
                    self.sv.handle_write_closed()
                    continue

                if self._wait in readable:
                    notification = os.read(self._wait, 4)

                    for c in notification:
                        assert not exit
                        if c == ord("v"):
                            # self.sv.write == validator.stdin
                            self.sv.write.close()
                            self.vs.propagate_eof = True
                            self.vs.handle_read_closed()
                            self.sv.handle_write_closed()
                        elif c == ord("s"):
                            # self.vs.write == submission.stdin
                            self.vs.write.close()
                            self.sv.propagate_eof = True
                            self.sv.handle_read_closed()
                            self.vs.handle_write_closed()
                        elif c == ord("x"):
                            exit = True
                        else:
                            assert False
                if self.vs.read in read and self.sv.read in read:
                    val = self.vs.read in readable
                    sub = self.sv.read in readable
                    if val != sub and (val, sub) != self._last:
                        self.switches += 1
                        self._last = (val, sub)

                for connection in (self.vs, self.sv):
                    if connection.read in readable:
                        connection.attemp_read()
                        connection.attemp_write()
                    elif connection.write in writeable:
                        connection.attemp_write()
        except (KeyboardInterrupt, Exception) as e:
            self.first_exception = e

    # this methods should only be called by the owner of the relay
    # i.e. the thread that created it
    def close_validator(self) -> None:
        if self._notify >= 0:
            os.write(self._notify, b"v")

    def close_submission(self) -> None:
        if self._notify >= 0:
            os.write(self._notify, b"s")

    def close(self) -> None:
        if self._notify >= 0:
            os.write(self._notify, b"x")
            os.close(self._notify)
            self._notify = -1
            self.join()
            os.close(self._wait)
            self._wait = -1
            if self.first_exception is not None:
                raise self.first_exception


USE_WAIT4: Final[bool] = hasattr(os, "wait4")
USE_RELAY: Final[bool] = not is_windows()


class Wait4:
    def __init__(self, gid: int) -> None:
        self.gid = gid

    def wait(self) -> tuple[int, int, float]:
        pid, status, rusage = os.wait4(-self.gid, 0)
        return pid, status, rusage.ru_utime + rusage.ru_stime


class ThreadedWait:
    def __init__(self, pids: Sequence[int]) -> None:
        self.finished = SimpleQueue[tuple[int, int, float] | Exception]()
        self.tstart = time.monotonic()

        def wait_thread(pid: int) -> None:
            try:
                res = os.waitpid(pid, 0)
                tend = time.monotonic()
                self.finished.put((*res, tend - self.tstart))
            except Exception as e:
                self.finished.put(e)

        for pid in pids:
            t = threading.Thread(target=wait_thread, args=(pid,), daemon=True)
            t.start()

    def wait(self) -> tuple[int, int, float]:
        res = self.finished.get()
        if isinstance(res, Exception):
            raise res
        return res


# Return a ExecResult object amended with verdict.
def run_interactive_test_case(
    run: "Run",
    bar: BAR_TYPE,
    *,
    # False: Return as part of ExecResult
    # True: print to stdout
    validator_error: bool = False,
    team_error: bool = False,
    # False: no output
    # True: stderr
    # else: path
    interaction: bool | Path = False,
    submission_args: Optional[Sequence[str | Path]] = None,
) -> Optional[ExecResult]:
    output_validators = run.problem.validators(OutputValidator)
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
        validator_command_str = "".join(map(str, validator_command))
        submission_command_str = "".join(map(str, submission_command))
        bar.log(f"Validator:  {validator_command_str}")
        bar.log(f"Submission: {submission_command_str}")

    # - Start validator
    # - Start submission, limiting CPU time to time_limit+1s
    # - Set timeout thread for submission and valdiator to kill if needed
    # - pump communication submission <-> validator, but delay submission EOF until submission dies
    # - Wait for either validator or submission to finish
    # - If the valdiator dies first:
    #   - If not AC: kill submission
    #   - close validator.stdin
    # - If the submission dies first:
    #   - If error -> not ac
    #   - Else wait for validator
    #
    # Note, with EOF propagation of validator to submision there is no reliable way to
    # distinguish the following two scenarios:
    # 1. submission crashes (RTE) -> writes invalid query -> validator juges (WA)
    # 2. validator judges (WA) -> submission can no longer read -> submission crashes (RTE)
    # But without this propagation pseudo interactive problem (where the validator sends EOF)
    # do not work... We just hope for the best

    if not USE_RELAY:
        if isinstance(interaction, Path):
            bar.warn("Cannot create .interaction file on windows")
        interaction = False

    if isinstance(interaction, Path):
        assert not interaction.is_relative_to(run.tmpdir)
    elif interaction:
        assert threading.current_thread() is threading.main_thread()

    with (
        interaction.open("a")
        if isinstance(interaction, Path)
        else nullcontext(sys.stderr if interaction else None) as interaction_file  # type: ignore[attr-defined]
    ):
        max_duration = 0.0
        tle_result = None
        for pass_id in itertools.count(1):
            # mixing os and subprocess functions is unsafe so we store which
            # PIDs have been reaped manually
            reaped: list[int] = []
            reaped_lock = threading.Lock()

            def close(pipe: Optional[IO[bytes]]) -> None:
                if pipe:
                    pipe.close()

            def kill(pid: int) -> None:
                with reaped_lock:
                    is_reaped = pid in reaped
                if not is_reaped:
                    with suppress(ProcessLookupError, PermissionError):
                        os.kill(pid, signal.SIGKILL)

            def clean_process(process: subprocess.Popen[bytes]) -> None:
                kill(process.pid)
                close(process.stdin)
                close(process.stdout)
                close(process.stderr)

            with ExitStack() as cleanup:
                try:
                    validator = subprocess.Popen(
                        validator_command,
                        bufsize=0,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        # TODO: Make a flag to pass validator error directly to terminal.
                        stderr=None if validator_error else subprocess.PIPE,
                        cwd=validator_dir,
                        preexec_fn=limit_setter(
                            validator_command,
                            validation_time,
                            validation_memory,
                            0,
                        ),
                    )
                    cleanup.callback(clean_process, validator)
                except (PermissionError, OSError) as e:
                    # File is likely not executable / probably doesn't exist.
                    return ExecResult(None, ExecStatus.ERROR, 0, False, str(e), None)

                # add all programs to the same group (for simplicity we take the pid of the validator)
                # then we can wait for all programs in the same group (only on unix)
                gid = validator.pid

                try:
                    submission = subprocess.Popen(
                        submission_command,
                        bufsize=0,
                        stdin=subprocess.PIPE if USE_RELAY else validator.stdout,
                        stdout=subprocess.PIPE if USE_RELAY else validator.stdin,
                        stderr=None if team_error else subprocess.PIPE,
                        cwd=submission_dir,
                        preexec_fn=limit_setter(submission_command, timeout, memory, gid),
                    )
                    cleanup.callback(clean_process, submission)
                except (PermissionError, OSError) as e:
                    # File is likely not executable / probably doesn't exist.
                    return ExecResult(None, ExecStatus.ERROR, 0, False, str(e), None)

                if USE_RELAY:
                    relay = Relay(interaction_file, validator, submission)
                    relay.start()
                    cleanup.callback(relay.close)
                else:
                    relay = None

                stop_kill_handler = threading.Event()
                cleanup.callback(stop_kill_handler.set)

                validator_time: Optional[float] = None
                submission_time: Optional[float] = None

                def kill_handler_function() -> None:
                    nonlocal validator_time, submission_time
                    if stop_kill_handler.wait(timeout + 1):
                        return
                    submission_time = timeout + 1.0
                    kill(submission.pid)
                    time_gap = validation_time - timeout + 1
                    if time_gap > 0 and stop_kill_handler.wait(time_gap):
                        return
                    validator_time = validation_time + 1.0
                    kill(validator.pid)

                kill_handler = threading.Thread(target=kill_handler_function, daemon=True)
                kill_handler.start()

                validator_status = None
                submission_status = None
                first: Optional[Literal["validator", "submission"]] = None
                wait = Wait4(gid) if USE_WAIT4 else ThreadedWait([validator.pid, submission.pid])
                while validator_status is None or submission_status is None:
                    pid, status, duration = wait.wait()
                    with reaped_lock:
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
                        if relay is not None:
                            relay.close_validator()
                        else:
                            close(validator.stdout)

                        # Possibly already written by the alarm.
                        if validator_time is None:
                            validator_time = duration

                        # Kill the team submission and everything else in case we already know it's WA.
                        if validator_status != config.RTV_AC:
                            stop_kill_handler.set()
                            kill(submission.pid)
                    else:
                        assert pid == submission.pid
                        if first is None:
                            first = "submission"
                        submission_status = status
                        if relay is not None:
                            relay.close_submission()
                        else:
                            close(validator.stdin)

                        # Possibly already written by the alarm.
                        if submission_time is None:
                            submission_time = duration

                stop_kill_handler.set()
                if relay is not None:
                    relay.close()

                val_err = None
                if validator.stderr is not None:
                    val_err = _feedback(run, validator.stderr.read())
                team_err = None
                if submission.stderr is not None:
                    team_err = submission.stderr.read().decode("utf-8", "replace")

            if not config.args.no_test_case_sanity_checks and relay is not None:
                switch_limit = 10**5
                if relay.switches > switch_limit:
                    bar.warn("observed over 10^5 context switches between submission and validator")
                transmission_limit = 10  # in MiB
                MiB = 1024**2
                if relay.vs.transmitted > transmission_limit * MiB:
                    bar.warn(f"Validator wrote over {transmission_limit}MiB")
                if (
                    validator_status == config.RTV_AC
                    and relay.sv.transmitted > transmission_limit * MiB
                ):
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
            # - else AC

            if validator_status not in [config.RTV_AC, config.RTV_WA]:
                if validator_time > validation_time:
                    bar.error(f"Validator TIMEOUT after {validator_time:.1f}s", resume=True)
                else:
                    config.n_error += 1
                verdict = Verdict.JUDGE_ERROR
            elif validator_status == config.RTV_WA and nextpass and nextpass.is_file():
                bar.error("got WRONG_ANSWER but found nextpass.in", resume=True)
                verdict = Verdict.JUDGE_ERROR
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
                    if not config.args.no_test_case_sanity_checks:
                        # we know that the validator did not read EOF because we delay this
                        bar.warn(
                            "Validator exited first with AC => Validator is unable to detect trailing output"
                        )
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
                bar.error("exceeded limit of validation_passes", resume=True)
                verdict = Verdict.JUDGE_ERROR
                break

            if interaction_file:
                print("---", file=interaction_file, flush=True)

    run._visualize_output(bar)

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
    res = err.decode("utf-8", "replace")
    if judgeerror.is_file():
        res = judgeerror.read_text(errors="replace")
    if len(res) == 0 and judgemessage.is_file():
        res = judgemessage.read_text(errors="replace")
    return res


# run the interactor without submission to see if it prints first
def interactor_prints_unprompted(
    problem: "Problem", test_case: "TestCase", wait: float = 0.1
) -> Optional[bool]:
    output_validators = problem.validators(OutputValidator)
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

    try:
        validator_process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=validator_dir,
        )
        time.sleep(wait)
        with suppress(ProcessLookupError, PermissionError):
            validator_process.kill()
        stdout, _ = validator_process.communicate()
        return bool(stdout)
    except (PermissionError, OSError):
        # File is likely not executable / probably doesn't exist.
        return None
