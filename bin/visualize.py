from pathlib import Path
from typing import Final, Optional, TYPE_CHECKING

import program
import testcase

from util import *

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from problem import Problem
    import run


class InputVisualizer(program.Program):
    """
    Visualizes a testcase, called as:

        ./visualizer input answer [args]

    """

    visualizer_type: Final[str] = "input"

    source_dir: Final[str] = "input_visualizer"

    def __init__(self, problem: "Problem", path: Path, **kwargs):
        super().__init__(
            problem,
            path,
            InputVisualizer.source_dir,
            limits={"timeout": problem.limits.visualizer_time},
            substitute_constants=True,
            **kwargs,
        )

    # Run the visualizer (should create a testcase.<ext> file).
    # Stdout is not used.
    def run(
        self, in_path: Path, ans_path: Path, cwd: Path, args: Optional[list[str]] = None
    ) -> ExecResult:
        assert self.run_command is not None, "Input Visualizer should be built before running it"

        return self._exec_command(
            self.run_command + [in_path, ans_path] + (args or []),
            cwd=cwd,
        )


class OutputVisualizer(program.Program):
    """
    Visualizes the output of a submission

        ./visualizer input answer feedbackdir [args] < output

    """

    visualizer_type: Final[str] = "output"

    source_dir: Final[str] = "output_visualizer"

    def __init__(self, problem: "Problem", path: Path, **kwargs):
        super().__init__(
            problem,
            path,
            OutputVisualizer.source_dir,
            limits={"timeout": problem.limits.visualizer_time},
            substitute_constants=True,
            **kwargs,
        )

    # Run the visualizer.
    # should write to feedbackdir/judgeimage.<ext>
    def run(
        self,
        testcase: testcase.Testcase,
        run: "run.Run",
        args: Optional[list[str]] = None,
    ) -> ExecResult:
        assert self.run_command is not None, "Output Visualizer should be built before running it"

        in_path = run.in_path  # relevant for multipass
        ans_path = testcase.ans_path.resolve()
        out_path = run.out_path
        cwd = run.feedbackdir

        with out_path.open("rb") as out_file:
            return self._exec_command(
                self.run_command + [in_path, ans_path, cwd] + (args or []),
                stdin=out_file,
                cwd=cwd,
            )


AnyVisualizer = InputVisualizer | OutputVisualizer
