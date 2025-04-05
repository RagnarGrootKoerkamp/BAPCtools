from pathlib import Path
from typing import TYPE_CHECKING

import program

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from problem import Problem


class InputVisualizer(program.Program):
    def __init__(self, problem: "Problem", path: Path, **kwargs):
        super().__init__(
            problem,
            path,
            "input_visualizer",
            limits={"timeout": problem.limits.visualizer_time},
            substitute_constants=True,
            **kwargs,
        )

    # Run the visualizer.
    # Stdout is not used.
    def run(self, cwd, stdin, args=[]):
        assert self.run_command is not None
        return self._exec_command(
            self.run_command + args,
            cwd=cwd,
            stdin=stdin,
        )
