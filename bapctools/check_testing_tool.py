import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Optional, TYPE_CHECKING

import vermin

from bapctools import config, parallel
from bapctools.program import Program
from bapctools.run import Submission
from bapctools.util import (
    command_supports_memory_limit,
    default_exec_code_map,
    ensure_symlink,
    error,
    ExecResult,
    ExecStatus,
    ProgressBar,
)

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools.problem import Problem

"""DISCLAIMER:

  This tool was only made to check testing tools faster.
  You should still carefully review the code of the testing tool.

  For this tool to work the following things must hold:
   - the testing tool must be found under `attachments/testing_tool.<ext>`
   - the testing tool must be callable as `{program} -f {in_path} {submission program}`
   - the testing tool must accept the downloadable samples as well as those found under
     `data/testing_tool_test/` as input files
   - the testing tool must exits with a non zero exit code if something goes wrong
   - the testing tool must not change the working directory
"""


EXPECTED_PYTHON_MINOR_VERSION: Final[int] = 9


class TestInput:
    def __init__(self, problem: "Problem", in_path: Path, short_path: Path) -> None:
        assert in_path.suffix in [".in", ".download", ".statement"]
        self.problem = problem
        self.in_path = in_path
        self.short_path = short_path
        if self.short_path.suffix in [".download", ".statement"]:
            ext = self.short_path.suffix
            name = self.short_path.with_suffix("")
            assert name.suffix in [".in"]
            self.name = str(name.with_suffix(ext))
        else:
            self.name = str(self.short_path.with_suffix(""))


class WrappedSubmission:
    def __init__(self, problem: "Problem", submission: Submission) -> None:
        self.problem = problem
        self.submission = submission
        self.name = submission.name
        self.tmpdir = (
            problem.tmpdir / "testing_tool" / submission.tmpdir.relative_to(problem.tmpdir)
        )
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.run_command: Optional[list[Path | str]] = None

    def supports_memory_limit(self) -> bool:
        assert self.run_command is not None
        assert self.submission.run_command is not None
        return command_supports_memory_limit(self.run_command) and command_supports_memory_limit(
            self.submission.run_command
        )

    def _wrapper_script(self) -> str:
        assert self.submission.run_command is not None
        args = ", ".join(map(repr, self.submission.run_command))
        # script assumes that the working directory is not changed
        script = """#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

result = subprocess.run(
    [{args}],
    stdout=sys.stdout,
    stderr=sys.stderr,
    stdin=sys.stdin,
)
returncode_file = Path(".returncode")
# For multipass we store the first non zero return code
write_returncode = True
if returncode_file.is_file():
    raw = returncode_file.read_text()
    try:
        if int(raw) != 0:
            write_returncode = False
    except ValueError:
        pass
if write_returncode:
    returncode_file.write_text(f"{result.returncode}\\n")
sys.exit(result.returncode)
"""
        return script.replace("{args}", args)

    def build(self) -> None:
        wrapper_file = self.tmpdir / "wrapper.py"
        wrapper_file.write_text(self._wrapper_script())
        self.run_command = [sys.executable, wrapper_file]

    def run(self, bar: ProgressBar, testing_tool: "TestingTool", testinput: TestInput) -> bool:
        assert self.run_command is not None
        rundir = self.tmpdir / testinput.short_path
        if rundir.is_file():
            rundir.unlink()
        elif rundir.exists():
            shutil.rmtree(rundir)
        rundir.mkdir(exist_ok=True, parents=True)

        returncode_file = rundir / ".returncode"
        in_path = rundir / "testcase.in"
        ensure_symlink(in_path, testinput.in_path)

        localbar = bar.start(testinput)

        result = testing_tool.run(in_path, self)
        submission_returncode = None
        submission_status = None
        if returncode_file.is_file():
            raw = returncode_file.read_text()
            try:
                submission_returncode = int(raw)
                submission_status = default_exec_code_map(submission_returncode)
            except ValueError:
                pass
        ok = bool(result.status) and bool(submission_status)

        message = []
        if result.status == ExecStatus.TIMEOUT:
            message.append("TIMEOUT")
        elif not result.status:
            message.append(f"Testing Tool exit code: {result.returncode}")
        if (
            submission_status is not None
            and not submission_status
            and submission_status != ExecStatus.TIMEOUT
        ):
            message.append(f"Submission exit code: {submission_returncode}")
        if not message:
            message.append("OK")

        data = ""
        if result.out and result.err:
            data = (
                "TESTING TOOL STDERR:"
                + localbar._format_data(result.err)
                + "\nTESTING TOOL STDOUT:"
                + localbar._format_data(result.out)
                + "\n"
            )
        elif result.err:
            data = result.err
        elif result.out:
            data = result.out

        localbar.done(ok, ", ".join(message), data)
        return ok


class TestingTool(Program):
    def __init__(self, problem: "Problem", path: Path) -> None:
        super().__init__(
            problem,
            path,
            "testing_tool",
            limits={
                "timeout": problem.limits.timeout,
                "memory": problem.limits.memory,
            },
        )

    def run(self, in_path: Path, submission: WrappedSubmission) -> ExecResult:
        assert self.run_command is not None
        assert submission.run_command is not None
        exec_res = self._exec_command(
            [*self.run_command, "-f", in_path, *submission.run_command],
            cwd=in_path.parent,
            crop=True,
            memory=self.limits["memory"] if submission.supports_memory_limit() else None,
        )
        return exec_res

    # this only works for single file python 3 files
    def check_python_version(self, bar: ProgressBar) -> None:
        if "python" not in self.language.name.lower():
            return
        if "3" not in self.language.name.lower():
            return
        if len(self.source_files) != 1:
            return
        source = self.source_files[0].read_text()

        vermin_conf = vermin.Config()
        vermin_conf.set_verbose(4)
        vermin_conf.set_only_show_violations(True)
        vermin_conf.add_target(
            (3, EXPECTED_PYTHON_MINOR_VERSION if config.args.verbose <= 1 else 0)
        )
        visitor = vermin.visit(source, vermin_conf, self.name)
        if not isinstance(visitor, vermin.SourceVisitor):
            bar.warn(f"Could not determine required python version for {self.name}")
            return
        version = visitor.minimum_versions()[1]
        if version in [None, 0, (0, 0)]:
            bar.warn(f"Could not determine required python version for {self.name}")
            return
        assert isinstance(version, tuple)
        version_str = vermin.dotted_name(version)
        minor = version[1]
        requirements = visitor.output_text().strip() if config.args.verbose else None
        if requirements and requirements.count("\n") <= 1:
            requirements = f"({requirements})"
        if minor > EXPECTED_PYTHON_MINOR_VERSION:
            bar.warn(f"seems compliant with python {version_str}", requirements)
        else:
            bar.log(
                f"requires python {version_str}. We advice requiring at most python 3.{EXPECTED_PYTHON_MINOR_VERSION}",
                requirements,
            )


def run(
    problem: "Problem", testinputs: Sequence[TestInput], submissions: Sequence[Submission]
) -> bool:
    wrapped_submissions = [WrappedSubmission(problem, submission) for submission in submissions]
    for submission in wrapped_submissions:
        submission.build()

    tool_dir = problem.path / "attachments" / "testing_tool"
    tool_files = list((problem.path / "attachments").glob("testing_tool.*"))
    if (tool_dir.is_dir() and tool_files) or len(tool_files) > 1:
        error("Multiple testing tools found!")
        return False
    elif not tool_dir.is_dir() and not tool_files:
        error("No testing tool found!")
        return False

    if tool_dir.is_dir():
        testing_tool = TestingTool(problem, tool_dir)
    else:
        testing_tool = TestingTool(problem, tool_files[0])

    bar = ProgressBar("Building testing tool", items=[testing_tool])
    localbar = bar.start(testing_tool)
    if not testing_tool.build(bar):
        localbar.done(False)
        return False
    testing_tool.check_python_version(localbar)
    localbar.done()
    bar.finalize(print_done=False)

    ok = True

    max_submission_len = max([len(x.name) for x in wrapped_submissions])
    max_testinput_len = max(len(x.name) for x in testinputs)

    # When True, the ProgressBar will print a newline before the first error log.
    needs_leading_newline = False if config.args.verbose else True
    for submission in wrapped_submissions:
        bar = ProgressBar(
            submission.name,
            count=len(testinputs),
            max_len=max_testinput_len + max_submission_len - len(submission.name),
            needs_leading_newline=needs_leading_newline,
        )
        cur_ok = True

        def run_submission(testinput: TestInput) -> None:
            nonlocal cur_ok
            # skip after first error
            if not cur_ok and not config.args.all:
                bar.skip()
                return
            if not submission.run(bar, testing_tool, testinput):
                # just writing False is thread safe
                cur_ok = False

        parallel.run_tasks(run_submission, testinputs, pin=True)
        ok &= cur_ok
        needs_leading_newline = bar.finalize()

    return ok
