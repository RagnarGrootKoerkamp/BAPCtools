""" Verdicts 

    Terminology
    -----------

    Write testgroup or testcase (as compound nouns). Avoid parsing test as a verb.

    testnode: a testgroup or testcase

"""

from pathlib import Path
import shutil
import sys
import testcase
from enum import Enum

from util import ProgressBar
import config
from colorama import Fore, Style


class Verdict(Enum):
    """The verdict of a testcase or testgroup"""

    ACCEPTED = 1
    WRONG_ANSWER = 2
    TIME_LIMIT_EXCEEDED = 3
    RUN_TIME_ERROR = 4


def path_for_testcase(tcase):
    return tcase.short_path.with_suffix('')


class Verdicts:
    """The verdicts of a submission.

    Attributes:
    testcases: a list of paths in lexicographic order
    testgroups: a list of paths in lexicographic order
    verdicts[testnode]: the verdict at the given testnode path, or None
    children[testgroup]: a list of child testnodes (as paths), not necessarily sorted
    first_error[testgroup]: the first child with non-ACCEPTED verdict; None if no such child exists
    unknowns[testgroup]: the children that do not (yet) have a verdict; as a list in sorted order
    """

    def __init__(self, testcases):
        self.testcases = sorted(path_for_testcase(tc) for tc in testcases)
        self.testgroups = sorted(set(path for tc in self.testcases for path in tc.parents))
        self.verdicts = {g: None for g in self.testcases + self.testgroups}

        self.children = {tg: [] for tg in self.testgroups}
        for path in self.testcases + self.testgroups:
            if path != Path('.'):
                self.children[path.parent].append(path)
        self.first_error = {tg: None for tg in self.testgroups}
        self.unknowns = {tg: sorted(self.children[tg]) for tg in self.testgroups}

    def set(self, tcase:testcase.Testcase, verdict):
        """ Set the verdict of the given testcase) """
        path = path_for_testcase(tcase)
        self._set_verdict_for_path(path, verdict)

    def child_verdicts(self, testgroup: Path) -> list[Verdict | None]:
        """
        Return the verdicts at the children of the given testgroup,
        lexicographically sorted by name of the child verdictable.
        """

        return sorted(self.verdicts(c) for c in sorted(self.children[testgroup]))

    def aggregate(self, testgroup: Path) -> Verdict:
        """The aggregate verdict at the given testgroup.
        Computes the lexicographically first non-accepted verdict.

        Raises:
        ValueError when missing child verdicts make the result ill-defined.
            For instance, [AC, RTE, None] is fine (the result is RTE), but
            [AC, None, RTE] is not (the first error cannot be determined).
        """
        verdicts = self.child_verdicts(testgroup)
        if all(v == Verdict.ACCEPTED for v in verdicts): # TODO there must be a way to oneline these four lines
            result = Verdict.ACCEPTED
        else:
            first_error = next(v for v in self.child_verdicts(testgroup) if v != Verdict.ACCEPTED)
            if first_error is None:
                raise ValueError(f"Verdict aggregation at {testgroup} with unknown child verdicts")
            result = first_error
        return result

    def _set_verdict_for_path(self, testnode: Path, verdict):
        if self.verdicts[testnode] is not None:
            raise ValueError(
                f"Overwriting verdict of {testnode} to {verdict} (was {self.verdicts[testnode]})"
            )
        self.verdicts[testnode] = verdict
        if testnode != Path('.'):
            # escalate verdict to parent(s) recursively, possibly inferring parental verdict(s)
            parent = testnode.parent
            self.unknowns[parent].remove(testnode) # TODO speed me up using binary search
            if verdict != Verdict.ACCEPTED and testnode < self.first_error[parent]:
                self.first_error[parent] = testnode
            if not self.unknowns[parent] or self.first_error[parent] < min(self.unknowns[parent]):
                # we can infer the verdict at the parent
                self._set_verdict_for_path(parent, self.aggregate(parent))


class VerdictTable:
    colors = {
        'ACCEPTED': Fore.GREEN,
        'WRONG_ANSWER': Fore.RED,
        'TIME_LIMIT_EXCEEDED': Fore.MAGENTA,
        'RUN_TIME_ERROR': Fore.YELLOW,
    }

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
        self.name_width = min(
            max_name_width, max([len(submission) for submission in self.submissions])
        )
        self.width = width if width >= self.name_width + 2 + 10 else -1
        self.last_width = 0
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

            # dont print table if it fills to much of the screen
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

    def next_submission(self):
        self.results.append(dict())
        self.current_testcases = set()

    def add_testcase(self, testcase):
        self.current_testcases.add(testcase)

    def finish_testcase(self, testcase, verdict):
        self.results[-1][testcase] = verdict
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

    def _get_verdict(self, s, testcase):
        res = Style.DIM + Fore.WHITE + '-' + Style.RESET_ALL
        if s < len(self.results):
            if testcase in self.results[s]:
                v = self.results[s][testcase]
                res = VerdictTable.colors[v]
                res += v[0].lower() if testcase in self.samples else v[0].upper()
            elif s + 1 == len(self.results) and testcase in self.current_testcases:
                res = Style.DIM + Fore.BLUE + '?'
        return res + Style.RESET_ALL

    def print(self, *, force=True, new_lines=2, printed_lengths=None):
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

                # group verdicts in parts of length at most ten
                verdicts = []
                for t, testcase in enumerate(self.testcases):
                    if t % 10 == 0:
                        verdicts.append([0, ''])
                    verdicts[-1][0] += 1
                    verdicts[-1][1] += self._get_verdict(s, testcase)

                printed = self.name_width + 1
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

    def done(self, success=True, message='', data=''):
        return super().done(success, message, data)

    def finalize(self, *, print_done=True, message=None):
        with self:
            res = super().finalize(print_done=print_done, message=message)
            self.table._clear(force=True)
            return res
