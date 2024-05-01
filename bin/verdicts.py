from pathlib import Path
import shutil
import sys
import threading
from enum import Enum

from util import ProgressBar
import config
import testcase
from colorama import Fore, Style


class Verdict(Enum):
    """The verdict of a testcase or testgroup"""

    ACCEPTED = 1
    WRONG_ANSWER = 2
    TIME_LIMIT_EXCEEDED = 3
    RUNTIME_ERROR = 4
    VALIDATOR_CRASH = 5
    COMPILER_ERROR = 6

    def __str__(self):
        return {
            Verdict.ACCEPTED: 'ACCEPTED',
            Verdict.WRONG_ANSWER: 'WRONG ANSWER',
            Verdict.TIME_LIMIT_EXCEEDED: 'TIME LIMIT EXCEEDED',
            Verdict.RUNTIME_ERROR: 'RUNTIME ERROR',
            Verdict.VALIDATOR_CRASH: 'VALIDATOR CRASH',
            Verdict.COMPILER_ERROR: 'COMPILER ERROR',
        }[self]

    def short(self):
        return {
            Verdict.ACCEPTED: 'AC',
            Verdict.WRONG_ANSWER: 'WA',
            Verdict.TIME_LIMIT_EXCEEDED: 'TLE',
            Verdict.RUNTIME_ERROR: 'RTE',
            Verdict.VALIDATOR_CRASH: 'VC',
            Verdict.COMPILER_ERROR: 'CE',
        }[self]

    def color(self):
        return {
            Verdict.ACCEPTED: Fore.GREEN,
            Verdict.WRONG_ANSWER: Fore.RED,
            Verdict.TIME_LIMIT_EXCEEDED: Fore.MAGENTA,
            Verdict.RUNTIME_ERROR: Fore.YELLOW,
            Verdict.VALIDATOR_CRASH: Fore.RED,
            Verdict.COMPILER_ERROR: Fore.RED,
        }[self]


class RunUntil(Enum):
    # Run until the lexicographically first error is known.
    FIRST_ERROR = 1
    # Run until the lexicographically first timeout testcase is known.
    DURATION = 2
    # Run all cases.
    ALL = 3


def to_char(v: Verdict | None | bool, lower=False):
    if v is None or v is False:
        return f'{Fore.BLUE}?{Style.RESET_ALL}'
    else:
        char = str(v)[0].lower() if lower else str(v)[0].upper()
        return f'{v.color()}{char}{Style.RESET_ALL}'


def to_string(v: Verdict | None | bool):
    if v is None or v is False:
        return to_char(v)
    else:
        return f'{v.color()}{str(v)}{Style.RESET_ALL}'


def from_string(s: str) -> Verdict:
    match s:
        case 'CORRECT' | 'ACCEPTED' | 'AC':
            return Verdict.ACCEPTED
        case 'WRONG-ANSWER' | 'WRONG_ANSWER' | 'WA':
            return Verdict.WRONG_ANSWER
        case 'TIMELIMIT' | 'TIME_LIMIT_EXCEEDED' | 'TLE':
            return Verdict.TIME_LIMIT_EXCEEDED
        case 'RUN-ERROR' | 'RUN_TIME_ERROR' | 'RUNTIME_ERROR' | 'RTE':
            return Verdict.RUNTIME_ERROR
        case 'NO-OUTPUT':
            return Verdict.WRONG_ANSWER
        case 'COMPILER-ERROR':
            return Verdict.COMPILER_ERROR
        case 'CHECK-MANUALLY':
            raise NotImplementedError
        case _:
            raise ValueError(f"Unknown verdict string {s}")


def from_string_domjudge(s: str) -> Verdict:
    match s:
        case 'CORRECT' | 'ACCEPTED':
            return Verdict.ACCEPTED
        case 'WRONG-ANSWER' | 'WRONG_ANSWER':
            return Verdict.WRONG_ANSWER
        case 'TIMELIMIT' | 'TIME_LIMIT_EXCEEDED':
            return Verdict.TIME_LIMIT_EXCEEDED
        case 'RUN-ERROR' | 'RUN_TIME_ERROR':
            return Verdict.RUNTIME_ERROR
        case 'NO-OUTPUT':
            return Verdict.WRONG_ANSWER
        case 'COMPILER-ERROR':
            return Verdict.COMPILER_ERROR
        case 'CHECK-MANUALLY':
            raise NotImplementedError
        case _:
            raise ValueError(f"Unknown DOMjudge verdict string {s}")


class Verdicts:
    """The verdicts of a submission.

    Testcases and testgroups are identified by strings.  In particular,
    * the testcase whose input file is 'a/b/1.in' is called 'a/b/1'
    * the two topmost testgroups are 'sample', 'secret'
    * the root is called '.'

    Initialised with all testcases. Individual verdicts are registered
    with set(), which infers verdicts upwards in the tree as they become
    available (and returns the topmost inferred testgroup).
    Verdicts (registered and inferred) are accessed with __getitem__

    >>> V = Verdicts(["a/b/1", "a/b/2", "a/c/1", "a/d/1", "b/3"], timeout=1.0)
    >>> V.set('a/b/1', 'ACCEPTED', 1.0)
    >>> V.set('a/b/2', 'AC', 1.0) # returns 'a/b' because that verdict will be set as well
    >>> print(V['a/b'], V['.'])
    ACCEPTED None

    Attributes:
    - run_until: Which testcases to run.
    - children[testgroup]: the lexicographically sorted list of direct children (testgroups and testcases) of the given testnode

    - verdict[testnode]: the verdict at the given testnode, or None. In particular,
        verdict['.'] is the root verdict, sometimes called final verdict or submission verdict.
        Should not be directly set; use __setitem__ on the Verdict object instead.

        None: not computed yet.
        False: determined to be unneeded.
    - duration[testcase]: the duration of the testcase
    """

    def __init__(
        self,
        testcases: list[testcase.Testcase],
        timeout: float = 1,
        run_until: RunUntil = RunUntil.FIRST_ERROR,
    ):
        testcases = {t.name for t in testcases}
        testgroups: set[str] = set(str(path) for tc in testcases for path in Path(tc).parents)

        # Lock operations reading/writing non-static data.
        # Private methods assume the lock is already locked when entering a public method.
        self.lock = threading.RLock()

        self.run_until = run_until
        self.timeout = timeout

        # (testcase | testgroup) -> Verdict | None | False
        self.verdict: dict[str, Verdict | None | False] = {g: None for g in testcases | testgroups}
        # testcase -> float | None
        self.duration: dict[str, float | None] = {g: None for g in testcases}

        # const testgroup -> [testgroup | testcase]
        self.children: dict[str, list[str]] = {node: [] for node in testgroups}
        for node in testcases | testgroups:
            if node != '.':
                parent = str(Path(node).parent)
                self.children[parent].append(node)
        for tg in self.children:
            self.children[tg] = sorted(self.children[tg])

    # Allow `with self` to lock.
    def __enter__(self):
        self.lock.__enter__()

    def __exit__(self, *args):
        self.lock.__exit__(*args)

    def is_testgroup(self, node) -> bool:
        """Is the given testnode name a testgroup (rather than a testcase)?
        This assumes nonempty testgroups.
        """
        return node in self.children

    def is_testcase(self, node) -> bool:
        """Is the given testnode name a testcase (rather than a testgroup)?
        This assumes nonempty testgroups.
        """
        return node not in self.children

    def set(self, testcase, verdict: str | Verdict, duration: float):
        """Set the verdict and duration of the given testcase (implying possibly others)

        verdict can be given as a Verdict or as a string using either long or
        short form ('ACCEPTED', 'AC', or Verdict.ACCEPTED).
        """
        with self:
            if isinstance(verdict, str):
                verdict = from_string(verdict)
            self.duration[testcase] = duration
            self._set_verdict_for_node(testcase, verdict, duration >= self.timeout)

    def __getitem__(self, testnode) -> Verdict | None:
        with self:
            return self.verdict[testnode]

    def salient_testcase(self) -> (str, float):
        """The testcase most salient to the root verdict.
        If self['.'] is Verdict.ACCEPTED, then this is the slowest testcase.
        Otherwise, it is the lexicographically first testcase that was rejected."""
        with self:
            match self['.']:
                case None:
                    raise ValueError("Salient testcase called before submission verdict determined")
                case Verdict.ACCEPTED:
                    # This implicitly assumes there is at least one testcase.
                    return max(
                        ((tc, d) for tc, d in self.duration.items() if d is not None),
                        key=lambda x: x[1],
                    )
                case _:
                    tc = min(
                        tc
                        for tc, v in self.verdict.items()
                        if self.is_testcase(tc) and v != Verdict.ACCEPTED
                    )
                    return (tc, self.duration[tc])

    def slowest_testcase(self) -> (str, float):
        """The slowest testcase, if all cases were run or a timeout occurred."""
        with self:
            tc, d = max(
                ((tc, d) for tc, d in self.duration.items() if d is not None), key=lambda x: x[1]
            )

            # If not all test cases were run and the max duration is less than the timeout,
            # we cannot claim that we know the slowest test case.
            if None in self.duration.values() and d < self.timeout:
                return None

            return tc, d

    def aggregate(self, testgroup: str) -> Verdict:
        """The aggregate verdict at the given testgroup.
        Computes the lexicographically first non-accepted verdict.

        Raises:
        ValueError when missing child verdicts make the result ill-defined.
            For instance, [AC, RTE, None] is fine (the result is RTE), but
            [AC, None, RTE] is not (the first error cannot be determined).
        """
        with self:
            child_verdicts = list(self.verdict[c] for c in self.children[testgroup])
            if all(v == Verdict.ACCEPTED for v in child_verdicts):
                return Verdict.ACCEPTED
            else:
                first_error = next(v for v in child_verdicts if v != Verdict.ACCEPTED)
                if first_error is None:
                    raise ValueError(
                        f"Verdict aggregation at {testgroup} with unknown child verdicts"
                    )
                return first_error

    def _set_verdict_for_node(self, testnode: str, verdict: Verdict, timeout: bool):
        # This assumes self.lock is already held.
        # Note that `False` verdicts can be overwritten if they were already started before being set to False.
        if self.verdict[testnode] not in [None, False]:
            raise ValueError(
                f"Overwriting verdict of {testnode} to {verdict} (was {self.verdict[testnode]})"
            )
        self.verdict[testnode] = verdict
        if testnode != '.':
            parent = str(Path(testnode).parent)

            # Possibly mark sibling cases as unneeded.
            match self.run_until:
                case RunUntil.FIRST_ERROR:
                    # On error, set all later siblings to False.
                    if verdict != Verdict.ACCEPTED:
                        for sibling in self.children[parent]:
                            if sibling > testnode and self.verdict[sibling] is None:
                                self.verdict[sibling] = False

                case RunUntil.DURATION:
                    # On timeout, set all later siblings to False.
                    if timeout:
                        for sibling in self.children[parent]:
                            if sibling > testnode and self.verdict[sibling] is None:
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

    def run_is_needed(self, testcase: str):
        """
        There are 3 modes for running cases:
        - default: run until the lexicographically first error is known
        - duration: run until the slowest case is known
        - all: run all cases

        Testcases/groups have their verdict set to `False` as soon as it is determined they are not needed.
        """
        with self:
            if self.verdict[testcase] is not None:
                return False

            match self.run_until:
                case RunUntil.FIRST_ERROR:
                    # Run only if parents do not have known verdicts yet.
                    return all(
                        self.verdict[str(parent)] is None for parent in Path(testcase).parents
                    )
                case RunUntil.DURATION:
                    # Run only if not explicitly marked as unneeded.
                    return all(
                        self.verdict[str(parent)] is not False for parent in Path(testcase).parents
                    )
                case RunUntil.ALL:
                    # Run all cases.
                    return True


class VerdictTable:
    def __init__(
        self,
        submissions,
        testcases,
        width=ProgressBar.columns,
        height=shutil.get_terminal_size().lines,
        max_name_width=50,
    ):
        self.submissions = [
            submission.name for verdict in submissions for submission in submissions[verdict]
        ]
        self.testcases = [t.name for t in testcases]
        self.samples = {t.name for t in testcases if t.root == 'sample'}
        self.results = []
        self.current_testcases = set()
        if config.args.tree:
            self.width = width if width >= 20 else -1
            self.last_printed = []
            self.print_without_force = not config.args.no_bar and config.args.overview
            self.checked_height = height
        else:
            self.name_width = min(
                max_name_width, max([len(submission) for submission in self.submissions])
            )
            self.width = width if width >= self.name_width + 2 + 10 else -1
            self.last_printed = []

            self.print_without_force = (
                not config.args.no_bar and config.args.overview and self.width >= 0
            )
            if self.print_without_force:
                # generate example lines for one submission
                name = 'x' * self.name_width
                lines = [f'{Style.DIM}{Fore.CYAN}{name}{Fore.WHITE}:']

                verdicts = []
                for t, testcase in enumerate(self.testcases):
                    if t % 10 == 0:
                        verdicts.append([0, ''])
                    verdicts[-1][0] += 1
                    verdicts[-1][1] += 's' if testcase in self.samples else '-'

                printed = self.name_width + 1
                for length, tmp in verdicts:
                    if printed + 1 + length > self.width:
                        lines.append(f'{str():{self.name_width+1}}')
                        printed = self.name_width + 1
                    lines[-1] += f' {tmp}'
                    printed += length + 1

                # dont print table if it fills too much of the screen
                self.print_without_force = len(lines) * len(self.submissions) + 5 < height
                if not self.print_without_force:
                    print(
                        f'{Fore.YELLOW}WARNING: Overview too large for terminal, skipping live updates{Style.RESET_ALL}',
                        file=sys.stderr,
                    )
                    print(
                        *lines,
                        f'[times {len(self.submissions)}...]',
                        Style.RESET_ALL,
                        sep='\n',
                        end='\n',
                        file=sys.stderr,
                    )

    def next_submission(self, verdicts: Verdicts):
        self.results.append(verdicts)
        self.current_testcases = set()

    def add_testcase(self, testcase):
        self.current_testcases.add(testcase)

    def update_verdicts(self, testcase, verdict, duration):
        self.results[-1].set(testcase, verdict, duration)
        self.current_testcases.discard(testcase)

    def _clear(self, *, force=True):
        if force or self.print_without_force:
            if self.last_printed:
                actual_width = ProgressBar.columns
                lines = sum(
                    max(1, (printed + actual_width - 1) // actual_width)
                    for printed in self.last_printed
                )

                print(
                    f'\033[{lines - 1}A\r\033[0J',
                    end='',
                    flush=True,
                    file=sys.stderr,
                )

                self.last_printed = []

    def _get_verdict(self, s, testcase, check_sample=True):
        res = f'{Fore.LIGHTBLACK_EX}-{Style.RESET_ALL}'
        if s < len(self.results) and self.results[s][testcase] not in [None, False]:
            res = to_char(self.results[s][testcase], check_sample and testcase in self.samples)
        elif s + 1 == len(self.results) and testcase in self.current_testcases:
            res = Style.DIM + to_char(None)
        return res

    def print(self, **kwargs):
        if config.args.tree:
            self._print_tree(**kwargs)
        else:
            self._print_table(**kwargs)

    def _print_tree(self, *, force=True, new_lines=1, printed_lengths=None):
        if printed_lengths is None:
            printed_lengths = []
        if force or self.print_without_force:
            printed_text = ['\n' * new_lines]
            printed_lengths += [0] * new_lines

            max_depth = None
            show_root = False

            stack = [('.', '', '', True)]
            while stack:
                node, indent, prefix, last = stack.pop()
                if node != '.' or show_root:
                    name = f'{node.split("/")[-1]}'
                    verdict = self.results[-1][node]
                    verdict_str = (
                        to_string(verdict)
                        if verdict is not False
                        else f'{Fore.LIGHTBLACK_EX}-{Style.RESET_ALL}'
                    )
                    printed_text.append(
                        f"{Fore.LIGHTBLACK_EX}{indent}{prefix}{Style.RESET_ALL}{name}: {verdict_str}\n"
                    )
                    if verdict in [None, False]:
                        verdict = '.'
                    printed_lengths.append(
                        len(indent) + len(prefix) + len(name) + 2 + len(str(verdict))
                    )
                if max_depth is not None and len(indent) >= 2 * max_depth:
                    continue
                pipe = ' ' if last else '│'
                first = True
                verdicts = []
                for child in reversed(self.results[-1].children[node]):
                    if self.results[-1].is_testgroup(child):
                        if first:
                            stack.append((child, indent + pipe + ' ', '└─', True))
                            first = False
                        else:
                            stack.append((child, indent + pipe + ' ', '├─', False))
                    else:
                        verdicts.append(self._get_verdict(len(self.results) - 1, child, False))
                if verdicts:
                    verdicts.reverse()
                    edge = '└' if first else '├'
                    pipe2 = ' ' if first else '│'

                    grouped = []
                    for i, verdict in enumerate(verdicts):
                        if i % 10 == 0:
                            grouped.append([0, ''])
                        grouped[-1][0] += 1
                        grouped[-1][1] += verdict

                    printed_text.append(
                        f'{Fore.LIGHTBLACK_EX}{indent}{pipe} {edge}─{Style.RESET_ALL}'
                    )
                    pref_len = len(indent) + len(pipe) + 1 + len(edge) + 1
                    printed = pref_len

                    width = -1 if ProgressBar.columns - pref_len < 10 else self.width
                    space = ''

                    for length, group in grouped:
                        if width >= 0 and printed + 1 + length > width:
                            printed_text.append(
                                f'\n{Fore.LIGHTBLACK_EX}{indent}{pipe} {pipe2} {Style.RESET_ALL}'
                            )
                            printed_lengths.append(printed)
                            printed = pref_len
                            space = ''

                        printed_text.append(f'{space}{group}')
                        printed += length + len(space)
                        space = ' '

                    printed_lengths.append(printed)
                    printed_text.append('\n')

            self._clear(force=True)

            if self.checked_height != True:
                if self.checked_height < len(printed_lengths) + 5:
                    print(
                        f'\033[0J{Fore.YELLOW}WARNING: Overview too large for terminal, skipping live updates{Style.RESET_ALL}\n',
                        file=sys.stderr,
                    )
                    self.print_without_force = False
                self.checked_height = True
                if not force and not self.print_without_force:
                    return

            print(''.join(printed_text), end='', flush=True, file=sys.stderr)
            self.last_printed = printed_lengths

    def _print_table(self, *, force=True, new_lines=2, printed_lengths=None):
        if printed_lengths is None:
            printed_lengths = []
        if force or self.print_without_force:
            printed_text = ['\n' * new_lines]
            printed_lengths += [0] * new_lines
            for s, submission in enumerate(self.submissions):
                # pad/truncate submission names to not break table layout
                name = submission
                if len(name) > self.name_width:
                    name = '...' + name[-self.name_width + 3 :]
                padding = ' ' * (self.name_width - len(name))
                printed_text.append(f'{Fore.CYAN}{name}{Style.RESET_ALL}:{padding}')
                printed = self.name_width + 1

                # group verdicts in parts of length at most ten
                verdicts = []
                for t, testcase in enumerate(self.testcases):
                    if t % 10 == 0:
                        verdicts.append([0, ''])
                    verdicts[-1][0] += 1
                    verdicts[-1][1] += self._get_verdict(s, testcase)

                for length, tmp in verdicts:
                    if self.width >= 0 and printed + 1 + length > self.width:
                        printed_text.append(f'\n{str():{self.name_width+1}}')
                        printed_lengths.append(printed)
                        printed = self.name_width + 1

                    printed_text.append(f' {tmp}')
                    printed += length + 1

                printed_lengths.append(printed)
                printed_text.append('\n')
            self._clear(force=True)
            print(''.join(printed_text), end='', flush=True, file=sys.stderr)
            self.last_printed = printed_lengths

    def ProgressBar(
        self, prefix, max_len=None, count=None, *, items=None, needs_leading_newline=False
    ):
        return TableProgressBar(
            self, prefix, max_len, count, items=items, needs_leading_newline=needs_leading_newline
        )


class TableProgressBar(ProgressBar):
    def __init__(self, table, prefix, max_len, count, *, items, needs_leading_newline):
        super().__init__(
            prefix, max_len, count, items=items, needs_leading_newline=needs_leading_newline
        )
        self.table = table

    # at the begin of any IO the progress bar locks so we can clear the table at this point
    def __enter__(self):
        super().__enter__()
        if ProgressBar.lock_depth == 1:
            self.reset_line_buffering = sys.stderr.line_buffering
            sys.stderr.reconfigure(line_buffering=False)
            self.table._clear(force=False)

    # at the end of any IO the progress bar unlocks so we can reprint the table at this point
    def __exit__(self, *args):
        if ProgressBar.lock_depth == 1:
            # ProgressBar.columns is just an educated guess for the number of printed chars
            # in the ProgressBar
            self.table.print(force=False, printed_lengths=[ProgressBar.columns])
            sys.stderr.reconfigure(line_buffering=self.reset_line_buffering)
            print(end='', flush=True, file=sys.stderr)
        super().__exit__(*args)

    def _print(self, *objects, sep='', end='\n', file=sys.stderr, flush=True):
        assert self._is_locked()
        # drop all flushes...
        print(*objects, sep=sep, end=end, file=file, flush=False)

    def start(self, item):
        self.table.add_testcase(item.testcase.name)
        return super().start(item)

    def done(self, success=True, message='', data='', print_item=True):
        return super().done(success, message, data, print_item)

    def finalize(self, *, print_done=True, message=None, suppress_newline=False):
        with self:
            res = super().finalize(
                print_done=print_done, message=message, suppress_newline=suppress_newline
            )
            self.table._clear(force=True)
            return res
