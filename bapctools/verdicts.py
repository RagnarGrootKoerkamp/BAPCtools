import io
import shutil
import sys
import threading
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional, TYPE_CHECKING

from colorama import Fore, Style

from bapctools import config, testcase
from bapctools.util import eprint, ITEM_TYPE, ProgressBar

if TYPE_CHECKING:
    from bapctools import run


class Verdict(Enum):
    """The verdict of a test case or test group"""

    ACCEPTED = 1
    WRONG_ANSWER = 2
    TIME_LIMIT_EXCEEDED = 3
    RUNTIME_ERROR = 4
    VALIDATOR_CRASH = 5
    COMPILER_ERROR = 6

    def __str__(self) -> str:
        return {
            Verdict.ACCEPTED: "ACCEPTED",
            Verdict.WRONG_ANSWER: "WRONG ANSWER",
            Verdict.TIME_LIMIT_EXCEEDED: "TIME LIMIT EXCEEDED",
            Verdict.RUNTIME_ERROR: "RUNTIME ERROR",
            Verdict.VALIDATOR_CRASH: "VALIDATOR CRASH",
            Verdict.COMPILER_ERROR: "COMPILER ERROR",
        }[self]

    def __lt__(self, other: "Verdict") -> bool:
        return self.value < other.value

    def short(self) -> str:
        return {
            Verdict.ACCEPTED: "AC",
            Verdict.WRONG_ANSWER: "WA",
            Verdict.TIME_LIMIT_EXCEEDED: "TLE",
            Verdict.RUNTIME_ERROR: "RTE",
            Verdict.VALIDATOR_CRASH: "VC",
            Verdict.COMPILER_ERROR: "CE",
        }[self]

    def color(self) -> str:
        return {
            Verdict.ACCEPTED: Fore.GREEN,
            Verdict.WRONG_ANSWER: Fore.RED,
            Verdict.TIME_LIMIT_EXCEEDED: Fore.MAGENTA,
            Verdict.RUNTIME_ERROR: Fore.YELLOW,
            Verdict.VALIDATOR_CRASH: Fore.RED,
            Verdict.COMPILER_ERROR: Fore.RED,
        }[self]


VERDICTS = [
    Verdict.ACCEPTED,
    Verdict.WRONG_ANSWER,
    Verdict.TIME_LIMIT_EXCEEDED,
    Verdict.RUNTIME_ERROR,
    Verdict.COMPILER_ERROR,
]


class RunUntil(Enum):
    # Run until the lexicographically first error is known.
    FIRST_ERROR = 1
    # Run until the lexicographically first timeout test case is known.
    DURATION = 2
    # Run all cases.
    ALL = 3


def to_char(v: Verdict | None | Literal[False], lower: bool = False) -> str:
    if v is None or v is False:
        return f"{Fore.BLUE}?{Style.RESET_ALL}"
    else:
        char = str(v)[0].lower() if lower else str(v)[0].upper()
        return f"{v.color()}{char}{Style.RESET_ALL}"


def to_string(v: Verdict | None | Literal[False]) -> str:
    if v is None or v is False:
        return to_char(v)
    else:
        return f"{v.color()}{str(v)}{Style.RESET_ALL}"


def from_string(s: str) -> Verdict:
    match s:
        case "CORRECT" | "ACCEPTED" | "AC":
            return Verdict.ACCEPTED
        case "WRONG-ANSWER" | "WRONG_ANSWER" | "WA":
            return Verdict.WRONG_ANSWER
        case "TIMELIMIT" | "TIME_LIMIT_EXCEEDED" | "TLE":
            return Verdict.TIME_LIMIT_EXCEEDED
        case "RUN-ERROR" | "RUN_TIME_ERROR" | "RUNTIME_ERROR" | "RTE":
            return Verdict.RUNTIME_ERROR
        case "NO-OUTPUT" | "NO":
            return Verdict.WRONG_ANSWER
        case "OUTPUT-LIMIT" | "OLE":
            return Verdict.RUNTIME_ERROR
        case "COMPILER-ERROR" | "CE":
            return Verdict.COMPILER_ERROR
        case "CHECK-MANUALLY":
            raise NotImplementedError
        case _:
            raise ValueError(f"Unknown verdict string {s}")


def from_string_domjudge(s: str) -> Verdict:
    match s:
        case "CORRECT" | "ACCEPTED":
            return Verdict.ACCEPTED
        case "WRONG-ANSWER" | "WRONG_ANSWER":
            return Verdict.WRONG_ANSWER
        case "TIMELIMIT" | "TIME_LIMIT_EXCEEDED":
            return Verdict.TIME_LIMIT_EXCEEDED
        case "RUN-ERROR" | "RUN_TIME_ERROR":
            return Verdict.RUNTIME_ERROR
        case "NO-OUTPUT":
            return Verdict.WRONG_ANSWER
        case "COMPILER-ERROR":
            return Verdict.COMPILER_ERROR
        case "CHECK-MANUALLY":
            raise NotImplementedError
        case _:
            raise ValueError(f"Unknown DOMjudge verdict string {s}")


class Verdicts:
    """The verdicts of a submission.

    Test cases and test groups are identified by strings.  In particular,
    * the test case whose input file is 'a/b/1.in' is called 'a/b/1'
    * the two topmost test groups are 'sample', 'secret'
    * the root is called '.'

    Initialised with all test cases. Individual verdicts are registered
    with set(), which infers verdicts upwards in the tree as they become
    available (and returns the topmost inferred test group).
    Verdicts (registered and inferred) are accessed with __getitem__

    >>> V = Verdicts(["a/b/1", "a/b/2", "a/c/1", "a/d/1", "b/3"], timeout=1)
    >>> V.set('a/b/1', 'ACCEPTED', 0.9)
    >>> V.set('a/b/2', 'AC', 0.9) # returns 'a/b' because that verdict will be set as well
    >>> print(V['a/b'], V['.'])
    ACCEPTED None

    Attributes:
    - run_until: Which test cases to run.
    - children[test_group]: the lexicographically sorted list of direct children (test groups and test cases) of the given test node
    - verdict[test_node]: the verdict at the given test node, or None. In particular,
        verdict['.'] is the root verdict, sometimes called final verdict or submission verdict.
        Should not be directly set; use __setitem__ on the Verdict object instead.

        None: not computed yet.
        False: determined to be unneeded.
    - duration[test_case]: the duration of the test case
    """

    def __init__(
        self,
        test_cases_list: Sequence[testcase.Testcase],
        timeout: int,
        run_until: RunUntil = RunUntil.FIRST_ERROR,
    ) -> None:
        test_cases: set[str] = set(t.name for t in test_cases_list)
        test_groups: set[str] = set(str(path) for tc in test_cases for path in Path(tc).parents)

        # Lock operations reading/writing non-static data.
        # Private methods assume the lock is already locked when entering a public method.
        self.lock = threading.RLock()

        self.run_until = run_until
        self.timeout = timeout

        # (test_case | test_group) -> Verdict | None | Literal[False]
        self.verdict: dict[str, Verdict | None | Literal[False]] = {
            g: None for g in test_cases | test_groups
        }
        # test_case -> float | None
        self.duration: dict[str, float | None] = {g: None for g in test_cases}

        # const test_group -> [test_group | test_case]
        self.children: dict[str, list[str]] = {node: [] for node in test_groups}
        for node in test_cases | test_groups:
            if node != ".":
                parent = str(Path(node).parent)
                self.children[parent].append(node)
        for tg in self.children:
            self.children[tg] = sorted(self.children[tg])

    # Allow `with self` to lock.
    def __enter__(self) -> None:
        self.lock.__enter__()

    def __exit__(self, *args: Any) -> None:
        self.lock.__exit__(*args)

    def is_test_group(self, node: str) -> bool:
        """Is the given test node name a test group (rather than a test case)?
        This assumes nonempty test groups.
        """
        return node in self.children

    def is_test_case(self, node: str) -> bool:
        """Is the given test node name a test case (rather than a test group)?
        This assumes nonempty test groups.
        """
        return node not in self.children

    def set(self, test_case: str, verdict: str | Verdict, duration: float) -> None:
        """Set the verdict and duration of the given test case (implying possibly others)

        verdict can be given as a Verdict or as a string using either long or
        short form ('ACCEPTED', 'AC', or Verdict.ACCEPTED).
        """
        with self:
            if isinstance(verdict, str):
                verdict = from_string(verdict)
            self.duration[test_case] = duration
            self._set_verdict_for_node(test_case, verdict, duration >= self.timeout)

    def __getitem__(self, test_node: str) -> Verdict | None | Literal[False]:
        with self:
            return self.verdict[test_node]

    def salient_test_case(self) -> tuple[str, float]:
        """The test case most salient to the root verdict.
        If self['.'] is Verdict.ACCEPTED, then this is the slowest test case.
        Otherwise, it is the lexicographically first test case that was rejected."""
        with self:
            match self["."]:
                case None:
                    raise ValueError(
                        "Salient test case called before submission verdict determined"
                    )
                case Verdict.ACCEPTED:
                    # This implicitly assumes there is at least one test case.
                    return max(
                        ((tc, d) for tc, d in self.duration.items() if d is not None),
                        key=lambda x: x[1],
                    )
                case _:
                    tc = min(
                        tc
                        for tc, v in self.verdict.items()
                        if self.is_test_case(tc) and v != Verdict.ACCEPTED
                    )
                    duration = self.duration[tc]
                    assert duration is not None
                    return (tc, duration)

    def slowest_test_case(self) -> None | tuple[str, float]:
        """The slowest test case, if all cases were run or a timeout occurred."""
        with self:
            tc, d = max(
                ((tc, d) for tc, d in self.duration.items() if d is not None),
                key=lambda x: x[1],
            )

            # If not all test cases were run and the max duration is less than the timeout,
            # we cannot claim that we know the slowest test case.
            if None in self.duration.values() and d < self.timeout:
                return None

            return tc, d

    def aggregate(self, test_group: str) -> Verdict:
        """The aggregate verdict at the given test group.
        Computes the lexicographically first non-accepted verdict.

        Raises:
        ValueError when missing child verdicts make the result ill-defined.
            For instance, [AC, RTE, None] is fine (the result is RTE), but
            [AC, None, RTE] is not (the first error cannot be determined).
        """
        with self:
            child_verdicts = list(self.verdict[c] for c in self.children[test_group])
            if all(v == Verdict.ACCEPTED for v in child_verdicts):
                return Verdict.ACCEPTED
            else:
                first_error = next(v for v in child_verdicts if v != Verdict.ACCEPTED)
                if first_error in [None, False]:
                    raise ValueError(
                        f"Verdict aggregation at {test_group} with unknown child verdicts"
                    )
                assert first_error is not None
                assert first_error is not False
                return first_error

    def _set_verdict_for_node(self, test_node: str, verdict: Verdict, timeout: bool) -> None:
        # This assumes self.lock is already held.
        if timeout:
            assert verdict != Verdict.ACCEPTED
        # Note that `False` verdicts can be overwritten if they were already started before being set to False.
        if self.verdict[test_node] not in [None, False]:
            raise ValueError(
                f"Overwriting verdict of {test_node} to {verdict} (was {self.verdict[test_node]})"
            )
        self.verdict[test_node] = verdict
        if test_node != ".":
            parent = str(Path(test_node).parent)

            # Possibly mark sibling cases as unneeded.
            match self.run_until:
                case RunUntil.FIRST_ERROR:
                    # On error, set all later siblings to False.
                    if verdict != Verdict.ACCEPTED:
                        for sibling in self.children[parent]:
                            if sibling > test_node and self.verdict[sibling] is None:
                                self.verdict[sibling] = False

                case RunUntil.DURATION:
                    # On timeout, set all later siblings to False.
                    if timeout:
                        for sibling in self.children[parent]:
                            if sibling > test_node and self.verdict[sibling] is None:
                                self.verdict[sibling] = False

                case RunUntil.ALL:
                    # Don't skip any cases.
                    pass

            # possibly update verdict at parent and escalate change upward recursively
            if self.verdict[parent] is None or self.verdict[parent] is False:
                try:
                    parentverdict = self.aggregate(parent)
                    self._set_verdict_for_node(parent, parentverdict, timeout)
                except ValueError:
                    # parent verdict cannot be determined yet
                    pass

    def run_is_needed(self, test_case: str) -> bool:
        """
        There are 3 modes for running cases:
        - default: run until the lexicographically first error is known
        - duration: run until the slowest case is known
        - all: run all cases

        Test cases/groups have their verdict set to `False` as soon as it is determined they are not needed.
        """
        with self:
            if self.verdict[test_case] is not None:
                return False

            match self.run_until:
                case RunUntil.FIRST_ERROR:
                    # Run only if parents do not have known verdicts yet.
                    return all(
                        self.verdict[str(parent)] is None for parent in Path(test_case).parents
                    )
                case RunUntil.DURATION:
                    # Run only if not explicitly marked as unneeded.
                    return all(
                        self.verdict[str(parent)] is not False for parent in Path(test_case).parents
                    )
                case RunUntil.ALL:
                    # Run all cases.
                    return True


class VerdictTable:
    class Group:
        def __init__(self, length: int, text: str) -> None:
            self.length = length
            self.text = text

        def tuple(self) -> tuple[int, str]:
            return (self.length, self.text)

    def __init__(
        self,
        submissions: Sequence["run.Submission"],
        test_cases: Sequence[testcase.Testcase],
        width: int = ProgressBar.columns,
        height: int = shutil.get_terminal_size().lines,
        max_name_width: int = 50,
    ) -> None:
        self.submissions: list[str] = [s.name for s in submissions]
        self.test_cases: list[str] = [t.name for t in test_cases]
        self.samples: set[str] = set(t.name for t in test_cases if t.root == "sample")
        self.results: list[Verdicts] = []
        self.current_test_cases: set[str] = set()
        self.last_printed: list[int] = []
        self.width: int
        self.print_without_force: bool
        if config.args.tree:
            self.width = width if width >= 20 else -1
            self.print_without_force = not config.args.no_bar and config.args.overview
            self.checked_height: int | bool = height
        else:
            self.name_width: int = min(
                max_name_width,
                max([len(submission) for submission in self.submissions]),
            )
            self.width = width if width >= self.name_width + 2 + 10 else -1

            self.print_without_force = (
                not config.args.no_bar and config.args.overview and self.width >= 0
            )
            if self.print_without_force:
                # generate example lines for one submission
                name = "x" * self.name_width
                lines = [f"{Style.DIM}{Fore.CYAN}{name}{Fore.WHITE}:"]

                verdicts = []
                for t, test_case in enumerate(self.test_cases):
                    if t % 10 == 0:
                        verdicts.append(VerdictTable.Group(0, ""))
                    verdicts[-1].length += 1
                    verdicts[-1].text += "s" if test_case in self.samples else "-"

                printed = self.name_width + 1
                for verdict_value in verdicts:
                    length, tmp = verdict_value.tuple()
                    if printed + 1 + length > self.width:
                        lines.append(f"{str():{self.name_width + 1}}")
                        printed = self.name_width + 1
                    lines[-1] += f" {tmp}"
                    printed += length + 1

                # dont print table if it fills too much of the screen
                self.print_without_force = len(lines) * len(self.submissions) + 5 < height
                if not self.print_without_force:
                    eprint(
                        f"{Fore.YELLOW}WARNING: Overview too large for terminal, skipping live updates{Style.RESET_ALL}"
                    )
                    eprint(
                        *lines,
                        f"[times {len(self.submissions)}...]",
                        Style.RESET_ALL,
                        sep="\n",
                        end="\n",
                    )

    def next_submission(self, verdicts: Verdicts) -> None:
        self.results.append(verdicts)
        self.current_test_cases = set()

    def add_test_case(self, test_case: str) -> None:
        self.current_test_cases.add(test_case)

    def update_verdicts(self, test_case: str, verdict: str | Verdict, duration: float) -> None:
        self.results[-1].set(test_case, verdict, duration)
        self.current_test_cases.discard(test_case)

    def _clear(self, *, force: bool = True) -> None:
        if force or self.print_without_force:
            if self.last_printed:
                actual_width = ProgressBar.columns
                lines = sum(
                    max(1, (printed + actual_width - 1) // actual_width)
                    for printed in self.last_printed
                )

                eprint(
                    f"\033[{lines - 1}A\r",
                    end="",
                    flush=True,
                )

                self.last_printed = []

    def _get_verdict(self, s: int, test_case: str, check_sample: bool = True) -> str:
        res = f"{Style.DIM}-{Style.RESET_ALL}"
        if s < len(self.results) and self.results[s][test_case] not in [None, False]:
            res = to_char(self.results[s][test_case], check_sample and test_case in self.samples)
        elif s + 1 == len(self.results) and test_case in self.current_test_cases:
            res = Style.DIM + to_char(None)
        return res

    def print(self, **kwargs: Any) -> None:
        if config.args.tree:
            self._print_tree(**kwargs)
        else:
            self._print_table(**kwargs)

    def _print_tree(
        self,
        *,
        force: bool = True,
        new_lines: int = 1,
        printed_lengths: list[int] | None = None,
    ) -> None:
        if printed_lengths is None:
            printed_lengths = []
        if force or self.print_without_force:
            printed_text = ["\n\033[2K" * new_lines]
            printed_lengths += [0] * new_lines

            max_depth = config.args.depth
            show_root = False

            stack = [(".", "", "", True)]
            while stack:
                node, indent, prefix, last = stack.pop()
                if node != "." or show_root:
                    name = f"{node.split('/')[-1]}"
                    verdict = self.results[-1][node]
                    verdict_str = (
                        to_string(verdict)
                        if verdict is not False
                        else f"{Style.DIM}-{Style.RESET_ALL}"
                    )
                    verdict_len = 1 if verdict in [None, False] else len(str(verdict))
                    printed_text.append(
                        f"{Style.DIM}{indent}{prefix}{Style.RESET_ALL}{name}: {verdict_str}\n\033[K"
                    )
                    printed_lengths.append(len(indent) + len(prefix) + len(name) + 2 + verdict_len)
                if max_depth is not None and len(indent) >= 2 * max_depth:
                    continue
                pipe = " " if last else "│"
                first = True
                verdicts = []
                for child in reversed(self.results[-1].children[node]):
                    if self.results[-1].is_test_group(child):
                        if first:
                            stack.append((child, indent + pipe + " ", "└╴", True))
                            first = False
                        else:
                            stack.append((child, indent + pipe + " ", "├╴", False))
                    else:
                        verdicts.append(self._get_verdict(len(self.results) - 1, child, False))
                if verdicts:
                    verdicts.reverse()
                    edge = "└" if first else "├"
                    pipe2 = " " if first else "│"

                    grouped = []
                    for i, v in enumerate(verdicts):
                        if i % 10 == 0:
                            grouped.append(VerdictTable.Group(0, ""))
                        grouped[-1].length += 1
                        grouped[-1].text += v

                    printed_text.append(f"{Style.DIM}{indent}{pipe} {edge}╴{Style.RESET_ALL}")
                    pref_len = len(indent) + len(pipe) + 1 + len(edge) + 1
                    printed = pref_len

                    width = -1 if ProgressBar.columns - pref_len < 10 else self.width
                    space = ""

                    for grouped_value in grouped:
                        length, group = grouped_value.tuple()
                        if width >= 0 and printed + 1 + length > width:
                            printed_text.append(
                                f"\n\033[K{Style.DIM}{indent}{pipe} {pipe2} {Style.RESET_ALL}"
                            )
                            printed_lengths.append(printed)
                            printed = pref_len
                            space = ""

                        printed_text.append(f"{space}{group}")
                        printed += length + len(space)
                        space = " "

                    printed_lengths.append(printed)
                    printed_text.append("\n\033[K")

            self._clear(force=True)

            if self.checked_height is not True:
                height = sum(
                    (w + ProgressBar.columns - 1) // ProgressBar.columns for w in printed_lengths
                )
                if self.checked_height < height + 5:
                    eprint(
                        f"\033[0J{Fore.YELLOW}WARNING: Overview too large for terminal, skipping live updates{Style.RESET_ALL}\n",
                    )
                    self.print_without_force = False
                self.checked_height = True
                if not force and not self.print_without_force:
                    return

            eprint(*printed_text, "\033[0J", sep="", end="", flush=True)
            self.last_printed = printed_lengths

    def _print_table(
        self,
        *,
        force: bool = True,
        new_lines: int = 2,
        printed_lengths: list[int] | None = None,
    ) -> None:
        if printed_lengths is None:
            printed_lengths = []
        if force or self.print_without_force:
            printed_text = ["\n\033[2K" * new_lines]
            printed_lengths += [0] * new_lines
            for s, submission in enumerate(self.submissions):
                # pad/truncate submission names to not break table layout
                name = submission
                if len(name) > self.name_width:
                    name = "..." + name[-self.name_width + 3 :]
                padding = " " * (self.name_width - len(name))
                printed_text.append(f"{Fore.CYAN}{name}{Style.RESET_ALL}:{padding}")
                printed = self.name_width + 1

                # group verdicts in parts of length at most ten
                verdicts = []
                for t, test_case in enumerate(self.test_cases):
                    if t % 10 == 0:
                        verdicts.append(VerdictTable.Group(0, ""))
                    verdicts[-1].length += 1
                    verdicts[-1].text += self._get_verdict(s, test_case)

                for verdict_value in verdicts:
                    length, tmp = verdict_value.tuple()
                    if self.width >= 0 and printed + 1 + length > self.width:
                        printed_text.append(f"\n\033[K{str():{self.name_width + 1}}")
                        printed_lengths.append(printed)
                        printed = self.name_width + 1

                    printed_text.append(f" {tmp}")
                    printed += length + 1

                printed_lengths.append(printed)
                printed_text.append("\n\033[K")
            self._clear(force=True)
            eprint(*printed_text, "\033[0J", sep="", end="", flush=True)
            self.last_printed = printed_lengths

    def ProgressBar(
        self,
        prefix: str,
        max_len: Optional[int] = None,
        count: Optional[int] = None,
        *,
        items: Optional[Sequence[ITEM_TYPE]] = None,
        needs_leading_newline: bool = False,
    ) -> "TableProgressBar":
        return TableProgressBar(
            self,
            prefix,
            max_len,
            count,
            items=items,
            needs_leading_newline=needs_leading_newline,
        )


class TableProgressBar(ProgressBar):
    def __init__(
        self,
        table: VerdictTable,
        prefix: str,
        max_len: Optional[int],
        count: Optional[int],
        *,
        items: Optional[Sequence[ITEM_TYPE]],
        needs_leading_newline: bool,
    ) -> None:
        super().__init__(
            prefix,
            max_len,
            count,
            items=items,
            needs_leading_newline=needs_leading_newline,
        )
        self.table = table

    # at the begin of any IO the progress bar locks so we can clear the table at this point
    def __enter__(self) -> None:
        super().__enter__()
        if ProgressBar.lock_depth == 1:
            if isinstance(sys.stderr, io.TextIOWrapper):
                self.reset_line_buffering = sys.stderr.line_buffering
                sys.stderr.reconfigure(line_buffering=False)
            self.table._clear(force=False)

    # at the end of any IO the progress bar unlocks so we can reprint the table at this point
    def __exit__(self, *args: Any) -> None:
        if ProgressBar.lock_depth == 1:
            # ProgressBar.columns is just an educated guess for the number of printed chars
            # in the ProgressBar
            self.table.print(force=False, printed_lengths=[ProgressBar.columns])
            if isinstance(sys.stderr, io.TextIOWrapper):
                sys.stderr.reconfigure(line_buffering=self.reset_line_buffering)
            eprint(end="", flush=True)
        super().__exit__(*args)

    def _print(self, *args: Any, **kwargs: Any) -> None:
        assert self._is_locked()
        kwargs.setdefault("sep", "")
        kwargs["flush"] = False  # drop all flushes...
        eprint(*args, **kwargs)

    def start(self, item: ITEM_TYPE = "") -> "TableProgressBar":
        from bapctools.run import Run

        assert isinstance(item, Run)
        self.table.add_test_case(item.testcase.name)
        copy = super().start(item)
        assert isinstance(copy, TableProgressBar)
        return copy

    def done(
        self,
        success: bool = True,
        message: str = "",
        data: Optional[str] = None,
        print_item: bool = True,
    ) -> None:
        super().done(success, message, data, print_item)

    def finalize(
        self,
        *,
        print_done: bool = True,
        message: Optional[str] = None,
        suppress_newline: bool = False,
    ) -> bool:
        with self:
            res = super().finalize(
                print_done=print_done,
                message=message,
                suppress_newline=suppress_newline,
            )
            self.table._clear(force=True)
            return res
