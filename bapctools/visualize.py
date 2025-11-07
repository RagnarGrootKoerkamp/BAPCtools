from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Optional, TYPE_CHECKING

from bapctools import program
from bapctools.util import ExecResult

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools.problem import Problem


class InputVisualizer(program.Program):
    """
    Visualizes a test case, called as:

        ./visualizer input answer [args]

    """

    visualizer_type: Final[str] = "input"

    source_dir: Final[str] = "input_visualizer"

    args_key: Final[str] = "input_visualizer_args"

    def __init__(self, problem: "Problem", path: Path, **kwargs: Any) -> None:
        super().__init__(
            problem,
            path,
            InputVisualizer.source_dir,
            limits={"timeout": problem.limits.visualizer_time},
            substitute_constants=True,
            **kwargs,
        )

    # Run the visualizer (should create a testcase.<ext> file).
    def run(
        self, in_path: Path, ans_path: Path, cwd: Path, args: Optional[Sequence[str | Path]] = None
    ) -> ExecResult:
        assert self.run_command is not None, "Input Visualizer should be built before running it"

        return self._exec_command(
            [*self.run_command, in_path, ans_path, *(args or [])],
            cwd=cwd,
        )


class OutputVisualizer(program.Program):
    """
    Visualizes the output of a submission

        ./visualizer input answer feedbackdir [args] < output

    """

    visualizer_type: Final[str] = "output"

    source_dir: Final[str] = "output_visualizer"

    args_key: Final[str] = "output_visualizer_args"

    def __init__(self, problem: "Problem", path: Path, **kwargs: Any) -> None:
        super().__init__(
            problem,
            path,
            OutputVisualizer.source_dir,
            limits={"timeout": problem.limits.visualizer_time},
            substitute_constants=True,
            **kwargs,
        )

    # Run the visualizer.
    # should write to feedbackdir/judgeimage.<ext> and/or feedbackdir/teamimage.<ext>
    def run(
        self,
        in_path: Path,
        ans_path: Path,
        out_path: Optional[Path],
        cwd: Path,
        args: Optional[Sequence[str | Path]] = None,
    ) -> ExecResult:
        assert self.run_command is not None, "Output Visualizer should be built before running it"
        assert (out_path is None) == self.problem.interactive, (
            "out_path should be None if and only if problem is interactive"
        )

        command = [*self.run_command, in_path, ans_path, cwd, *(args or [])]
        if out_path is not None:
            with out_path.open("rb") as out_file:
                return self._exec_command(command, stdin=out_file, cwd=cwd)
        else:
            return self._exec_command(command, cwd=cwd)


AnyVisualizer = InputVisualizer | OutputVisualizer
