import copy
import functools
import os
import shutil
import signal
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn, Optional, ParamSpec, Protocol, TypeVar

from colorama import Fore, Style
from typing_extensions import override, Self

from bapctools import config


# we almost always want to print to stderr
# for legacy reasons this is intentionally not synchronized with the bar!
# (this would break the TableProgressBar)
def eprint(*args: Any, **kwargs: Any) -> None:
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


def exit1(force: bool = False) -> NoReturn:
    if force:
        sys.stdout.close()
        sys.stderr.close()
        # exit even more forcefully to ensure that daemon threads dont break something
        os._exit(1)
    else:
        sys.exit(1)


if hasattr(signal, "SIGWINCH"):
    COLUMNS: int = shutil.get_terminal_size().columns
    CARRIAGE_RETURN: str = "\033[K"

    def update_columns(_: Any, __: Any) -> None:
        global COLUMNS
        COLUMNS = shutil.get_terminal_size().columns

    signal.signal(signal.SIGWINCH, update_columns)
else:
    COLUMNS = shutil.get_terminal_size().columns - 1
    CARRIAGE_RETURN = " " * COLUMNS + "\r"


class Named(Protocol):
    @property
    def name(self) -> str: ...


ItemType = str | Path | Named


def item_text(item: Optional[ItemType]) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if isinstance(item, Path):
        return str(item)
    return item.name


def item_len(item: ItemType) -> int:
    return len(item_text(item))


def action(
    prefix: Optional[str],
    item: Optional[ItemType],
    width: Optional[int] = None,
    total_width: Optional[int] = None,
) -> str:
    if width is not None and total_width is not None:
        if prefix is None and width > total_width:
            width = total_width
        if prefix is not None and len(prefix) + 2 + width > total_width:
            width = total_width - len(prefix) - 2
    text = item_text(item)
    if width is not None:
        text = text[:width]
    if width is None or width < 0:
        width = 0
    prefix = "" if prefix is None else f"{Fore.CYAN}{prefix}{Style.RESET_ALL}: "
    return f"{prefix}{text:<{width}}"


def process_warning(message: str, item: Optional[ItemType]) -> str:
    item_name = action(None, item, None, None)
    if item_name and f"{item_name} {message}" in config.args.ignore_warning:
        return f"{message} (ignored)"
    if message in config.args.ignore_warning:
        return f"{message} (ignored)"
    config.n_warn += 1
    return message


def crop_output(output: str) -> str:
    if config.args.error:
        return output

    lines = output.split("\n")
    numlines = len(lines)
    cropped = False
    # Cap number of lines
    if numlines > 30:
        output = "\n".join(lines[:25]) + "\n"
        cropped = True

    # Cap total length.
    if len(output) > 2000:
        output = f"{output[:2000]}[...]\n"
        cropped = True

    if cropped:
        output += f"{Fore.YELLOW}Use -e to show more.{Style.RESET_ALL}"
    return output


def format_data(data: Optional[str]) -> str:
    if not data:
        return ""
    prefix = "  " if "\n" not in data.removesuffix("\n") else "\n"
    data = crop_output(data).removesuffix("\n")
    return f"{prefix}{Fore.YELLOW}{data}{Style.RESET_ALL}"


# The base functionallity of a bar, i.e., printing stuff
# Note that this intentionally does not contain functions
# to change the item, i.e., no start, done, finalize. This
# has to be done by an actual bar
class BaseBar(ABC):
    # Lock on all IO via this class.
    lock = threading.RLock()
    lock_depth = 0

    def __init__(
        self, prefix: Optional[str], max_len: Optional[int], item: Optional[ItemType] = None
    ) -> None:
        self.prefix: Optional[str] = prefix
        self.max_len: Optional[int] = max_len
        self.item: Optional[ItemType] = item
        self.item_width: Optional[int] = None

        if item is not None:
            assert prefix is not None
            self.item_width = item_len(item) + 1
        if max_len is not None:
            self.item_width = max_len + 1

    def __enter__(self) -> None:
        BaseBar.lock.__enter__()
        BaseBar.lock_depth += 1

    def __exit__(self, *args: Any) -> None:
        BaseBar.lock_depth -= 1
        BaseBar.lock.__exit__(*args)

    def _is_locked(self) -> bool:
        return BaseBar.lock_depth > 0

    @abstractmethod
    def _log(self, message: str, data: Optional[str] = None, color: str = Fore.GREEN) -> None: ...

    def log(self, message: str, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
        self._log(message, data, color)

    # Same as log, but only in verbose mode.
    def verbose(self, message: str, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
        if config.args.verbose:
            self._log(message, data, color)

    def warn(self, message: str, data: Optional[str] = None) -> None:
        if config.args.suppress_warnings < 1:
            with self:
                message = process_warning(message, self.item)
                self._log(message, data, Fore.YELLOW)

    def error(self, message: str, data: Optional[str] = None) -> None:
        if config.args.suppress_warnings < 2:
            with self:
                config.n_error += 1
                self._log(message, data, Fore.RED)

    def fatal(
        self, message: str, data: Optional[str] = None, *, force: Optional[bool] = None
    ) -> NoReturn:
        if force is None:
            force = threading.active_count() > 1
        with self:
            config.n_error += 1
            self._log(message, data, Fore.RED)
            exit1(force=force)

    # Log an intermediate line if it's an error or we're in verbose mode.
    def part_done(
        self,
        success: bool = True,
        message: str = "",
        data: Optional[str] = None,
        *,
        warn_instead_of_error: bool = False,
    ) -> None:
        if not success:
            assert message
            if warn_instead_of_error:
                process_warning(message, self.item)
            else:
                config.n_error += 1
        if config.args.verbose or not success:
            with self:
                if success:
                    self.log(message, data)
                elif warn_instead_of_error:
                    self.warn(message, data)
                else:
                    self.error(message, data)


class EmptyBar(BaseBar):
    def __init__(self) -> None:
        super().__init__(None, None)

    @override
    def _log(self, message: str, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
        with self:
            eprint(color, message, format_data(data), Style.RESET_ALL, sep="")

    @override
    def log(self, message: str, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
        super().log(f"LOG: {message}", data, color)

    @override
    def verbose(self, message: str, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
        super().verbose(f"VERBOSE: {message}", data, color)

    @override
    def warn(self, message: str, data: Optional[str] = None) -> None:
        if config.args.suppress_warnings < 1:
            with self:
                message = process_warning(message, None)
                self.log(f"WARNING: {message}", data, Fore.YELLOW)

    @override
    def error(self, message: str, data: Optional[str] = None) -> None:
        super().error(f"ERROR: {message}", data)

    @override
    def fatal(
        self, message: str, data: Optional[str] = None, *, force: Optional[bool] = None
    ) -> NoReturn:
        super().fatal(f"FATAL ERROR: {message}", data)


class ProgressBarLocal(threading.local):
    def __init__(self) -> None:
        self.item: Optional[ItemType] = None
        self.logged: bool = False

    def log(self) -> None:
        if self.item:
            self.logged = True


# A class that draws a progressbar.
# Construct with a constant prefix, the max length of the items to process, and
# the number of items to process.
# When count is None, the bar itself isn't shown.
# Start each item with bar.start(current_item), end it with bar.done(message).
# Optionally, multiple errors can be logged using the normal bar operations like
# bar.log(), bar.error(), etc.
# If anything was logged the final message on bar.done() will be suppressed.
class ProgressBar(BaseBar):
    current_bar: Optional["ProgressBar"] = None

    # When needs_leading_newline is True, this will print an additional empty line before the first log message.
    def __init__(
        self,
        prefix: str,
        max_len: Optional[int] = None,
        count: Optional[int] = None,
        *,
        items: Optional[Sequence[ItemType]] = None,
        needs_leading_newline: bool = False,
    ) -> None:
        assert ProgressBar.current_bar is None, ProgressBar.current_bar.prefix
        ProgressBar.current_bar = self

        assert not (items and (max_len or count))
        assert items is not None or max_len
        if items is not None and max_len is None:
            max_len = max((item_len(x) for x in items), default=0)
        assert max_len is not None

        super().__init__(prefix, max_len)

        self.count: Optional[int] = count  # The number of items we're processing
        self.i: int = 0
        self.needs_leading_newline: bool = needs_leading_newline
        self.logged: bool = False
        self.in_progress: set[ItemType] = set()
        # thread local data used between bar.start() and bar.done()
        self.local = ProgressBarLocal()

    def _print(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("sep", "")
        kwargs.setdefault("flush", True)
        eprint(*args, **kwargs)

    def bar_width(self) -> int:
        assert self.prefix is not None
        assert self.item_width is not None
        return COLUMNS - len(self.prefix) - 2 - self.item_width

    def clearline(self) -> None:
        assert self._is_locked()
        if config.args.no_bar:
            return
        self._print(CARRIAGE_RETURN, end="", flush=False)

    def get_prefix(self, local: bool = False) -> str:
        item = self.local.item if local else self.item
        return action(self.prefix, item, self.item_width, COLUMNS)

    def get_bar(self) -> str:
        bar_width = self.bar_width()
        if self.count is None or bar_width < 4:
            return ""
        # self.i is the number of started items
        done = (self.i - 1) * (bar_width - 2) // self.count
        text = f" {self.i}/{self.count}"
        fill = "#" * done + "-" * (bar_width - 2 - done)
        if len(text) <= len(fill):
            fill = fill[: -len(text)] + text
        return f"[{fill}]"

    def draw_bar(self) -> None:
        assert self._is_locked()
        if config.args.no_bar:
            return
        bar = self.get_bar()
        prefix = self.get_prefix()
        if bar == "":
            self._print(prefix, end="\r")
        else:
            self._print(prefix, bar, end="\r")

    # Remove the current item from in_progress.
    def _release_item(self) -> None:
        assert self.local.item is not None
        self.in_progress.remove(self.local.item)
        if self.local.item is self.item:
            self.item = None
        self.local.item = None

    # Resume the ongoing progress bar after a log/done.
    def _resume(self) -> None:
        assert self._is_locked()
        if config.args.no_bar:
            return
        if self.item not in self.in_progress:
            self.item = next(iter(self.in_progress), None)
        self.draw_bar()

    # Log can be called multiple times to make multiple persistent lines.
    # Make sure that the message does not end in a newline.
    @override
    def _log(self, message: str, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
        with self:
            self.clearline()
            self.logged = True
            self.local.log()

            if self.needs_leading_newline:
                self._print()
                self.needs_leading_newline = False

            self._print(
                self.get_prefix(local=True),
                color,
                message,
                format_data(data),
                Style.RESET_ALL,
            )
            self._resume()

    # Skip an item.
    def skip(self) -> None:
        with self:
            self.i += 1
            self.draw_bar()

    # For parallel contexts, start() will return a copy to preserve the item name.
    # The parent still holds some global state:
    # - global_logged
    # - the counter
    # - items in progress
    def start(self, item: ItemType) -> None:
        assert self.local.item is None
        with self:
            self.i += 1
            assert self.count is None or self.i <= self.count, (
                f"Starting more items than the max of {self.count}"
            )

            self.item = item
            self.local.item = item
            self.local.logged = False
            self.in_progress.add(item)
            self.draw_bar()

    # Log a final line if it's an error or if nothing was printed yet and we're in verbose mode.
    def done(
        self,
        success: bool = True,
        message: str = "",
        data: Optional[str] = None,
        *,
        print_item: bool = True,
        force_log: bool = False,
    ) -> None:
        assert self.local.item is not None
        if not success:
            assert message
        with self:
            self.clearline()
            if not print_item:
                self._release_item()

            if not self.local.logged:
                if not success:
                    config.n_error += 1
                if config.args.verbose or not success or force_log:
                    self.log(
                        message,
                        data,
                        color=Fore.GREEN if success else Fore.RED,
                    )

            if print_item:
                self._release_item()
            self._resume()

    # Print a final 'Done' message in case nothing was printed yet.
    # When 'message' is set, always print it.
    def finalize(
        self,
        *,
        print_done: bool = True,
        message: Optional[str] = None,
        suppress_newline: bool = False,
    ) -> None:
        with self:
            self.clearline()
            assert self.count is None or self.i == self.count, (
                f"Bar has done only {self.i} of {self.count} items"
            )
            assert self.item is None
            assert self.local.item is None
            assert not self.in_progress

            # At most one of print_done and message may be passed.
            if message:
                assert print_done is True

            # If nothing was logged, we don't need the super wide spacing before the final 'DONE'.
            if not self.local.logged and not message:
                self.item_width = 0

            # Print 'DONE' when nothing was printed yet but a summary was requested.
            if print_done and not self.logged and not message:
                message = f"{Fore.GREEN}Done{Style.RESET_ALL}"

            if message:
                self._print(self.get_prefix(), message)

            # When something was printed, add a newline between parts.
            if (self.logged or message) and not suppress_newline:
                self._print()

        assert ProgressBar.current_bar is not None
        ProgressBar.current_bar = None


# A simple bar that holds a constant prefix and item
class PrintBar(BaseBar):
    def __init__(
        self,
        prefix: str,
        max_len: Optional[int] = None,
        *,
        item: Optional[ItemType] = None,
    ) -> None:
        super().__init__(prefix, max_len, item)
        self.logged: bool = False
        self.parent: Optional[PrintBar] = None

    def _set_logged(self) -> None:
        if self.logged:
            return
        self.glogged = True
        if self.parent is not None:
            self.parent._set_logged()

    @override
    def _log(self, message: str, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
        with self:
            self._set_logged()
            prefix = action(self.prefix, self.item, self.item_width, None)
            eprint(prefix, color, message, format_data(data), Style.RESET_ALL, sep="")

    def with_item(self, item: ItemType) -> Self:
        bar_copy = copy.copy(self)
        bar_copy.item = item
        bar_copy.item_width = max(bar_copy.item_width or 0, item_len(item) + 1)
        if bar_copy.max_len is not None:
            bar_copy.item_width = bar_copy.max_len + 1
        bar_copy.parent = self
        bar_copy.logged = False
        return bar_copy


# global bar state
global_bar: BaseBar = EmptyBar()

P = ParamSpec("P")
R = TypeVar("R")


def restore(func: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(func)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        global global_bar
        assert not isinstance(global_bar, ProgressBar)
        old_bar = global_bar
        try:
            return func(*args, **kwargs)
        finally:
            global_bar = old_bar

    return wrapped


def make_global(bar: BaseBar) -> None:
    global global_bar
    global_bar = bar


# allow using the bar module the same way as a BaseBar
def part_done(
    success: bool = True,
    message: str = "",
    data: Optional[str] = None,
    *,
    warn_instead_of_error: bool = False,
) -> None:
    global_bar.part_done(success, message, data, warn_instead_of_error=warn_instead_of_error)


def log(msg: Any, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
    global_bar.log(msg, data, color=color)


def verbose(msg: Any, data: Optional[str] = None, color: str = Fore.GREEN) -> None:
    global_bar.verbose(msg, data, color=color)


def warn(msg: Any, data: Optional[str] = None) -> None:
    global_bar.warn(msg, data)


def error(msg: Any, data: Optional[str] = None) -> None:
    global_bar.error(msg)


def fatal(msg: Any, data: Optional[str] = None, *, force: Optional[bool] = None) -> NoReturn:
    global_bar.fatal(msg, data, force=force)
