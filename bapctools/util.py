# read problem settings from config files

import copy
import errno
import hashlib
import os
import re
import secrets
import shutil
import signal
import string
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import (
    Any,
    cast,
    Iterable,
    Literal,
    NoReturn,
    Optional,
    overload,
    Protocol,
    TYPE_CHECKING,
    TypeAlias,
    TypeVar,
)
from uuid import UUID

from colorama import Fore, Style
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.constructor import DuplicateKeyError

from bapctools import config

if TYPE_CHECKING:  # Prevent circular import: https://stackoverflow.com/a/39757388
    from bapctools.problem import Problem
    from bapctools.verdicts import Verdict


try:
    import questionary
    from prompt_toolkit.document import Document

    has_questionary = True

    class EmptyValidator(questionary.Validator):
        def validate(self, document: Document) -> None:
            if len(document.text) == 0:
                raise questionary.ValidationError(message="Please enter a value")

except Exception:
    has_questionary = False


def is_windows() -> bool:
    return sys.platform in ["win32", "cygwin"]


def is_mac() -> bool:
    return sys.platform in ["darwin"]


def is_freebsd() -> bool:
    return "freebsd" in sys.platform


def is_aquabsd() -> bool:
    return "aquabsd" in sys.platform


def is_bsd() -> bool:
    return is_mac() or is_freebsd() or is_aquabsd()


if not is_windows():
    import resource


def exit1(force: bool = False) -> NoReturn:
    if force:
        sys.stdout.close()
        sys.stderr.close()
        # exit even more forcefully to ensure that daemon threads dont break something
        os._exit(1)
    else:
        sys.exit(1)


# we almost always want to print to stderr
def eprint(*args: Any, **kwargs: Any) -> None:
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


def debug(*msg: Any) -> None:
    eprint(Fore.CYAN, end="")
    eprint("DEBUG:", *msg, end="")
    eprint(Style.RESET_ALL)


def log(msg: Any) -> None:
    eprint(f"{Fore.GREEN}LOG: {msg}{Style.RESET_ALL}")


def verbose(msg: Any) -> None:
    if config.args.verbose >= 1:
        eprint(f"{Fore.CYAN}VERBOSE: {msg}{Style.RESET_ALL}")


def warn(msg: Any) -> None:
    eprint(f"{Fore.YELLOW}WARNING: {msg}{Style.RESET_ALL}")
    config.n_warn += 1


def error(msg: Any) -> None:
    if config.RUNNING_TEST:
        fatal(msg)
    eprint(f"{Fore.RED}ERROR: {msg}{Style.RESET_ALL}")
    config.n_error += 1


def fatal(msg: Any, *, force: Optional[bool] = None) -> NoReturn:
    if force is None:
        force = threading.active_count() > 1
    eprint(f"\n{Fore.RED}FATAL ERROR: {msg}{Style.RESET_ALL}")
    exit1(force)


class MessageType(Enum):
    LOG = 1
    WARN = 2
    ERROR = 3
    FATAL = 4

    def __str__(self) -> str:
        return {
            MessageType.LOG: str(Fore.GREEN),
            MessageType.WARN: str(Fore.YELLOW),
            MessageType.ERROR: str(Fore.RED),
            MessageType.FATAL: str(Fore.RED),
        }[self]


class Named(Protocol):
    name: str


ITEM_TYPE: TypeAlias = str | Path | Named


# A class that draws a progressbar.
# Construct with a constant prefix, the max length of the items to process, and
# the number of items to process.
# When count is None, the bar itself isn't shown.
# Start each loop with bar.start(current_item), end it with bar.done(message).
# Optionally, multiple errors can be logged using bar.log(error). If so, the
# final message on bar.done() will be ignored.
class ProgressBar:
    # Lock on all IO via this class.
    lock = threading.RLock()
    lock_depth = 0

    current_bar: Optional["ProgressBar"] = None

    columns = shutil.get_terminal_size().columns

    if not is_windows():

        def update_columns(_: Any, __: Any) -> None:
            cols, rows = shutil.get_terminal_size()
            ProgressBar.columns = cols

        signal.signal(signal.SIGWINCH, update_columns)

    @staticmethod
    def item_text(item: Optional[ITEM_TYPE]) -> str:
        if item is None:
            return ""
        if isinstance(item, str):
            return item
        if isinstance(item, Path):
            return str(item)
        return item.name

    @staticmethod
    def item_len(item: ITEM_TYPE) -> int:
        return len(ProgressBar.item_text(item))

    def _is_locked(self) -> bool:
        return ProgressBar.lock_depth > 0

    # When needs_leading_newline is True, this will print an additional empty line before the first log message.
    def __init__(
        self,
        prefix: str,
        max_len: Optional[int] = None,
        count: Optional[int] = None,
        *,
        items: Optional[Sequence[ITEM_TYPE]] = None,
        needs_leading_newline: bool = False,
    ) -> None:
        assert ProgressBar.current_bar is None, ProgressBar.current_bar.prefix
        ProgressBar.current_bar = self

        assert not (items and (max_len or count))
        assert items is not None or max_len
        if items is not None and max_len is None:
            max_len = max((ProgressBar.item_len(x) for x in items), default=0)
        assert max_len is not None
        self.prefix: str = prefix  # The prefix to always print
        self.item_width: int = max_len + 1  # The max length of the items we're processing
        self.count: Optional[int] = count  # The number of items we're processing
        self.i: int = 0
        emptyline = " " * self.total_width() + "\r"
        self.carriage_return: str = emptyline if is_windows() else "\033[K"
        self.logged: bool = False
        self.global_logged: bool = False

        # For parallel contexts, start() will return a copy to preserve the item name.
        # The parent still holds some global state:
        # - global_logged
        # - IO lock
        # - the counter
        # - items in progress
        self.parent: Optional["ProgressBar"] = None
        self.in_progress: set[ITEM_TYPE] = set()
        self.item: Optional[ITEM_TYPE] = None

        self.needs_leading_newline: bool = needs_leading_newline

    def __enter__(self) -> None:
        ProgressBar.lock.__enter__()
        ProgressBar.lock_depth += 1

    def __exit__(self, *args: Any) -> None:
        ProgressBar.lock_depth -= 1
        ProgressBar.lock.__exit__(*args)

    def _print(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("sep", "")
        kwargs.setdefault("flush", True)
        eprint(*args, **kwargs)

    def total_width(self) -> int:
        cols = ProgressBar.columns
        if is_windows():
            cols -= 1
        return cols

    def bar_width(self) -> int:
        return self.total_width() - len(self.prefix) - 2 - self.item_width

    def update(self, count: int, max_len: int) -> None:
        assert self.count is not None
        self.count += count
        self.item_width = max(self.item_width, max_len + 1) if self.item_width else max_len + 1

    def add_item(self, item: ITEM_TYPE) -> None:
        assert self.count is not None
        self.count += 1
        self.item_width = max(self.item_width, ProgressBar.item_len(item))

    def clearline(self) -> None:
        if config.args.no_bar:
            return
        assert self._is_locked()
        self._print(self.carriage_return, end="", flush=False)

    @staticmethod
    def action(
        prefix: Optional[str],
        item: Optional[ITEM_TYPE],
        width: Optional[int] = None,
        total_width: Optional[int] = None,
        print_item: bool = True,
    ) -> str:
        if width is not None and total_width is not None:
            if prefix is None and width > total_width:
                width = total_width
            if prefix is not None and len(prefix) + 2 + width > total_width:
                width = total_width - len(prefix) - 2
        text = ProgressBar.item_text(item)
        if width is not None and len(text) > width:
            text = text[:width]
        if width is None or width <= 0:
            width = 0
        prefix = "" if prefix is None else f"{Fore.CYAN}{prefix}{Style.RESET_ALL}: "
        suffix = f"{text:<{width}}" if print_item else " " * width
        return prefix + suffix

    def get_prefix(self, print_item: bool = True) -> str:
        return ProgressBar.action(
            self.prefix, self.item, self.item_width, self.total_width(), print_item
        )

    def get_bar(self) -> str:
        bar_width = self.bar_width()
        if self.count is None or bar_width is None or bar_width < 4:
            return ""
        done = (self.i - 1) * (bar_width - 2) // self.count
        text = f" {self.i}/{self.count}"
        fill = "#" * done + "-" * (bar_width - 2 - done)
        if len(text) <= len(fill):
            fill = fill[: -len(text)] + text
        return "[" + fill + "]"

    def draw_bar(self) -> None:
        assert self._is_locked()
        if config.args.no_bar:
            return
        bar = self.get_bar()
        prefix = self.get_prefix()
        if bar is None or bar == "":
            self._print(prefix, end="\r")
        else:
            self._print(prefix, bar, end="\r")

    # Remove the current item from in_progress.
    def _release_item(self) -> None:
        assert self.item is not None
        if self.parent:
            self.parent.in_progress.remove(self.item)
            if self.parent.item is self.item:
                self.parent.item = None
        else:
            self.in_progress.remove(self.item)
        self.item = None

    # Resume the ongoing progress bar after a log/done.
    # Should only be called for the root.
    def _resume(self) -> None:
        assert self._is_locked()
        assert self.parent is None

        if config.args.no_bar:
            return

        if len(self.in_progress) > 0:
            if self.item is None or self.item not in self.in_progress:
                self.item = next(iter(self.in_progress))
            self.draw_bar()

    def start(self, item: ITEM_TYPE = "") -> "ProgressBar":
        with self:
            # start may only be called on the root bar.
            assert self.parent is None
            self.i += 1
            assert self.count is None or self.i <= self.count, (
                f"Starting more items than the max of {self.count}"
            )

            # assert self.item is None
            self.item = item
            self.logged = False
            self.in_progress.add(item)
            bar_copy = copy.copy(self)
            bar_copy.parent = self

            self.draw_bar()
            return bar_copy

    @staticmethod
    def _format_data(data: Optional[str]) -> str:
        if not data:
            return ""
        prefix = "  " if data.count("\n") <= 1 else "\n"
        return prefix + Fore.YELLOW + strip_newline(crop_output(data)) + Style.RESET_ALL

    # Log can be called multiple times to make multiple persistent lines.
    # Make sure that the message does not end in a newline.
    def log(
        self,
        message: str,
        data: Optional[str] = None,
        color: str = Fore.GREEN,
        *,
        resume: bool = True,
        print_item: bool = True,
    ) -> None:
        with self:
            self.clearline()
            self.logged = True

            if self.parent:
                self.parent.global_logged = True
                if self.parent.needs_leading_newline:
                    self._print()
                    self.parent.needs_leading_newline = False
            else:
                self.global_logged = True
                if self.needs_leading_newline:
                    self._print()
                    self.needs_leading_newline = False

            self._print(
                self.get_prefix(print_item),
                color,
                message,
                ProgressBar._format_data(data),
                Style.RESET_ALL,
            )

            if resume:
                if self.parent:
                    self.parent._resume()
                else:
                    self._resume()

    # Same as log, but only in verbose mode.
    def debug(
        self,
        message: str,
        data: Optional[str] = None,
        color: str = Fore.GREEN,
        *,
        resume: bool = True,
        print_item: bool = True,
    ) -> None:
        if config.args.verbose:
            self.log(message, data, color, resume=resume, print_item=print_item)

    def warn(self, message: str, data: Optional[str] = None, *, print_item: bool = True) -> None:
        with self.lock:
            config.n_warn += 1
            self.log(message, data, Fore.YELLOW, print_item=print_item)

    # Error by default removes the current item from the in_progress set.
    # Set `resume` to `True` to continue processing the item.
    def error(
        self,
        message: str,
        data: Optional[str] = None,
        *,
        resume: bool = False,
        print_item: bool = True,
    ) -> None:
        with self:
            config.n_error += 1
            self.log(message, data, Fore.RED, resume=resume, print_item=print_item)
            if not resume:
                self._release_item()

    # Skip an item.
    def skip(self) -> None:
        with self:
            self.i += 1

    # Log a final line if it's an error or if nothing was printed yet and we're in verbose mode.
    def done(
        self,
        success: bool = True,
        message: str = "",
        data: Optional[str] = None,
        print_item: bool = True,
    ) -> None:
        with self:
            self.clearline()

            if self.item is None:
                return

            if not self.logged:
                if not success:
                    config.n_error += 1
                if config.args.verbose or not success:
                    self.log(
                        message,
                        data,
                        color=Fore.GREEN if success else Fore.RED,
                        print_item=print_item,
                    )

            self._release_item()
            if self.parent:
                self.parent._resume()

    # Log an intermediate line if it's an error or we're in verbose mode.
    # Return True when something was printed
    def part_done(
        self,
        success: bool = True,
        message: str = "",
        data: Optional[str] = None,
        warn_instead_of_error: bool = False,
    ) -> bool:
        if not success:
            if warn_instead_of_error:
                config.n_warn += 1
            else:
                config.n_error += 1
        if config.args.verbose or not success:
            with self:
                if success:
                    self.log(message, data)
                else:
                    if warn_instead_of_error:
                        self.warn(message, data)
                    else:
                        self.error(message, data, resume=True)
                if self.parent:
                    self.parent._resume()
            return True
        return False

    # Print a final 'Done' message in case nothing was printed yet.
    # When 'message' is set, always print it.
    def finalize(
        self,
        *,
        print_done: bool = True,
        message: Optional[str] = None,
        suppress_newline: bool = False,
    ) -> bool:
        with self:
            self.clearline()
            assert self.parent is None
            assert self.count is None or self.i == self.count, (
                f"Bar has done only {self.i} of {self.count} items"
            )
            assert self.item is None
            # At most one of print_done and message may be passed.
            if message:
                assert print_done is True

            # If nothing was logged, we don't need the super wide spacing before the final 'DONE'.
            if not self.global_logged and not message:
                self.item_width = 0

            # Print 'DONE' when nothing was printed yet but a summary was requested.
            if print_done and not self.global_logged and not message:
                message = f"{Fore.GREEN}Done{Style.RESET_ALL}"

            if message:
                self._print(self.get_prefix(), message)

            # When something was printed, add a newline between parts.
            if self.global_logged and not suppress_newline:
                self._print()

        assert ProgressBar.current_bar is not None
        ProgressBar.current_bar = None

        return self.global_logged and not suppress_newline


# A simple bar that only holds a task prefix
class PrintBar:
    def __init__(
        self,
        prefix: Optional[str | Path] = None,
        max_len: Optional[int] = None,
        *,
        item: Optional[ITEM_TYPE] = None,
    ) -> None:
        self.prefix = str(prefix) if prefix else None
        self.item_width = None
        if item is not None:
            self.item_width = ProgressBar.item_len(item) + 1
        if max_len is not None:
            self.item_width = max_len + 1
        self.item = item

    def start(self, item: Optional[ITEM_TYPE] = None) -> "PrintBar":
        bar_copy = copy.copy(self)
        bar_copy.item = item
        return bar_copy

    def log(
        self,
        message: str,
        data: Optional[str] = None,
        color: str = Fore.GREEN,
        *,
        resume: bool = True,
        print_item: bool = True,
    ) -> None:
        prefix = ProgressBar.action(self.prefix, self.item, self.item_width, None, print_item)
        eprint(prefix, color, message, ProgressBar._format_data(data), Style.RESET_ALL, sep="")

    def debug(
        self,
        message: str,
        data: Optional[str] = None,
        color: str = Fore.GREEN,
        *,
        resume: bool = True,
        print_item: bool = True,
    ) -> None:
        if config.args.verbose:
            self.log(message, data, color, resume=resume, print_item=print_item)

    def warn(self, message: str, data: Optional[str] = None, *, print_item: bool = True) -> None:
        config.n_warn += 1
        self.log(message, data, Fore.YELLOW, print_item=print_item)

    def error(
        self,
        message: str,
        data: Optional[str] = None,
        *,
        resume: bool = False,
        print_item: bool = True,
    ) -> None:
        config.n_error += 1
        self.log(message, data, Fore.RED, print_item=print_item)

    def fatal(
        self,
        message: str,
        data: Optional[str] = None,
        *,
        resume: bool = False,
        print_item: bool = True,
    ) -> None:
        config.n_error += 1
        self.log(message, data, Fore.RED, resume=resume, print_item=print_item)
        exit1()


BAR_TYPE = PrintBar | ProgressBar


# Given a command line argument, return the first match:
# - absolute
# - relative to the 'type' directory for the current problem
# - relative to the problem directory
# - relative to the contest directory
# - relative to the current working directory
#
# Pass suffixes = ['.in'] to also try to find the file with the given suffix appended.
def get_basedirs(problem: "Problem", type: str | Path) -> list[Path]:
    p = problem.path
    return [p / type, p, p.parent, config.current_working_directory]


# Python 3.9
# True when child is a Path inside parent Path.
# Both must be absolute.
def is_relative_to(parent: Path, child: Path) -> bool:
    return child == parent or parent in child.parents


def resolve_path_argument(
    problem: "Problem", path: Path, type: str | Path, suffixes: list[str] = []
) -> Optional[Path]:
    if path.is_absolute():
        return path
    for suffix in suffixes + [None]:
        suffixed_path = path if suffix is None else path.with_suffix(suffix)
        for basedir in get_basedirs(problem, type):
            p = basedir / suffixed_path
            if p.exists():
                return p
    warn(f"{path} not found")
    return None


# creates a shortened path to some file/dir in the tmpdir.
# If the provided path does not point to the tmpdir it is returned as is.
# The path is of the form "tmp/<contest_tmpdir>/<problem_tmpdir>/links/<hash>"
def shorten_path(problem: "Problem", path: Path) -> Path:
    if not path.resolve().is_relative_to(problem.tmpdir):
        return path
    short_hash = hashlib.sha256(bytes(path)).hexdigest()[-6:]
    dir = problem.tmpdir / "links"
    dir.mkdir(parents=True, exist_ok=True)
    short_path = dir / short_hash
    ensure_symlink(short_path, path)
    return short_path


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    else:
        return sum(f.stat().st_size for f in path.rglob("*") if f.exists())


def drop_suffix(path: Path, suffixes: Sequence[str]) -> Path:
    for suffix in suffixes:
        if path.name.endswith(suffix):
            return path.with_name(path.name.removesuffix(suffix))
    return path


# Drops the first two path components <problem>/<type>/
def print_name(path: Path, keep_type: bool = False) -> str:
    return str(Path(*path.parts[1 if keep_type else 2 :]))


ryaml = YAML(typ="rt")
ryaml.default_flow_style = False
ryaml.indent(mapping=2, sequence=4, offset=2)
ryaml.width = sys.maxsize
ryaml.preserve_quotes = True

# For some reason ryaml.load doesn't work well in parallel.
read_ruamel_lock = threading.Lock()


def parse_yaml(data: str, path: Optional[Path] = None, *, suppress_errors: bool = False) -> object:
    with read_ruamel_lock:
        try:
            ret = ryaml.load(data)
        except DuplicateKeyError as e:
            if suppress_errors:
                return None
            if path is not None:
                fatal(f"Duplicate key in yaml file {path}!\n{e.args[0]}\n{e.args[2]}")
            else:
                fatal(f"Duplicate key in yaml object!\n{str(e)}")
        except Exception as e:
            if suppress_errors:
                return None
            eprint(f"{Fore.YELLOW}{e}{Style.RESET_ALL}", end="")
            fatal(f"Failed to parse {path}.")
    return ret


def read_yaml(path: Path, *, suppress_errors: bool = False) -> object:
    assert path.is_file(), f"File {path} does not exist"
    return parse_yaml(path.read_text(), path=path, suppress_errors=suppress_errors)


def normalize_yaml_value(value: object, t: type[object]) -> object:
    if isinstance(value, str) and t is Path:
        value = Path(value)
    if isinstance(value, int) and t is float:
        value = float(value)
    return value


class YamlParser:
    T = TypeVar("T")

    def __init__(
        self,
        source: str,
        yaml: dict[object, object],
        parent_path: Optional[str] = None,
        bar: BAR_TYPE = PrintBar(),
    ):
        assert isinstance(yaml, dict)
        self.errors = 0
        self.source = source
        self.yaml = yaml
        self.parent_path = parent_path
        self.parent_str = "root" if parent_path is None else f"`{parent_path}`"
        self.bar = bar

    def _key_path(self, key: str) -> str:
        return key if self.parent_path is None else f"{self.parent_path}.{key}"

    def check_unknown_keys(self) -> None:
        for key in self.yaml:
            if not isinstance(key, str):
                self.bar.warn(f"invalid {self.source} key: {key} in {self.parent_str}")
            else:
                self.bar.warn(f"found unknown {self.source} key: {key} in {self.parent_str}")

    def pop(self, key: str) -> object:
        return self.yaml.pop(key, None)

    def extract_optional(self, key: str, t: type[T]) -> Optional[T]:
        if key in self.yaml:
            value = normalize_yaml_value(self.yaml.pop(key), t)
            if value is None or isinstance(value, t):
                return value
            self.bar.warn(
                f"incompatible value for key `{self._key_path(key)}` in {self.source}. SKIPPED."
            )
        return None

    def extract(self, key: str, default: T, constraint: Optional[str] = None) -> T:
        value = self.extract_optional(key, type(default))
        result = default if value is None else value
        if constraint:
            assert isinstance(result, (float, int))
            assert eval(f"{default} {constraint}")
            if not eval(f"{result} {constraint}"):
                self.bar.warn(
                    f"value for `{self._key_path(key)}` in {self.source} should be {constraint} but is {result}. SKIPPED."
                )
                return default
        return result

    def extract_and_error(self, key: str, t: type[T]) -> T:
        if key in self.yaml:
            value = normalize_yaml_value(self.yaml.pop(key), t)
            if isinstance(value, t):
                return value
            self.bar.error(f"incompatible value for key '{key}' in {self.source}.")
        else:
            self.bar.error(f"missing key `{self._key_path(key)}` in {self.source}.")
        self.errors += 1
        return t()

    def extract_deprecated(self, key: str, new: Optional[str] = None) -> None:
        if key in self.yaml:
            use = f", use `{new}` instead" if new else ""
            self.bar.warn(f"key `{self._key_path(key)}` is deprecated{use}. SKIPPED.")
            self.yaml.pop(key)

    def extract_optional_list(
        self, key: str, t: type[T], *, allow_value: bool = True, allow_empty: bool = False
    ) -> list[T]:
        if key in self.yaml:
            value = self.yaml.pop(key)
            if value is None:
                return []
            if allow_value and isinstance(value, t):
                return [value]
            if isinstance(value, list):
                if not all(isinstance(v, t) for v in value):
                    self.bar.warn(
                        f"some values for key `{self._key_path(key)}` in {self.source} do not have type {t.__name__}. SKIPPED."
                    )
                    return []
                if not value and not allow_empty:
                    self.bar.warn(
                        f"value for `{self._key_path(key)}` in {self.source} should not be an empty list."
                    )
                return value
            self.bar.warn(
                f"incompatible value for key `{self._key_path(key)}` in {self.source}. SKIPPED."
            )
        return []

    def extract_parser(self, key: str) -> "YamlParser":
        return YamlParser(self.source, self.extract(key, {}), self._key_path(key), self.bar)


U = TypeVar("U")


@overload
def ryaml_get_or_add(yaml: CommentedMap, key: str) -> CommentedMap: ...
@overload
def ryaml_get_or_add(yaml: CommentedMap, key: str, t: type[U]) -> U: ...
def ryaml_get_or_add(
    yaml: CommentedMap,
    key: str,
    t: type[CommentedMap] | type[U] = CommentedMap,
) -> CommentedMap | U:
    assert isinstance(yaml, CommentedMap)
    if key not in yaml or yaml[key] is None:
        yaml[key] = t()
    value = yaml[key]
    assert isinstance(value, t)
    return cast(CommentedMap | U, value)


# This tries to preserve the correct comments.
def ryaml_filter(data: CommentedMap, remove: str) -> object:
    assert isinstance(data, CommentedMap)
    remove_index = list(data.keys()).index(remove)
    if remove_index == 0:
        return data.pop(remove)

    curr = data
    prev_key = list(data.keys())[remove_index - 1]
    while isinstance(curr[prev_key], (list, dict)) and len(curr[prev_key]):
        # Try to remove the comment from the last element in the preceding list/dict
        curr = curr[prev_key]
        if isinstance(curr, list):
            prev_key = len(curr) - 1
        else:
            prev_key = list(curr.keys())[-1]

    if remove in data.ca.items:
        # Move the comment that belongs to the removed key (which comes _after_ the removed key)
        # to the preceding key
        curr.ca.items[prev_key] = data.ca.items.pop(remove)
    elif prev_key in curr.ca.items:
        # If the removed key does not have a comment,
        # the comment after the previous key should be removed
        curr.ca.items.pop(prev_key)

    return data.pop(remove)


# Insert a new key before an old key, then remove the old key.
# If new_value is not given, the default is to simply rename the old key to the new key.
def ryaml_replace(
    data: CommentedMap,
    old_key: str,
    new_key: str,
    new_value: object = None,
) -> None:
    assert isinstance(data, CommentedMap)
    if new_value is None:
        new_value = data[old_key]
    data.insert(list(data.keys()).index(old_key), new_key, new_value)
    data.pop(old_key)
    if old_key in data.ca.items:
        data.ca.items[new_key] = data.ca.items.pop(old_key)


# Only allow one thread to write at the same time. Else, e.g., generating test cases in parallel goes wrong.
write_yaml_lock = threading.Lock()


# The @overload definitions are purely here for static typing reasons.
@overload
def write_yaml(data: object, path: None = None) -> str: ...
@overload
def write_yaml(data: object, path: Path) -> None: ...
def write_yaml(data: object, path: Optional[Path] = None) -> Optional[str]:
    with write_yaml_lock:
        _path = StringIO() if path is None else path
        ryaml.dump(
            data,
            _path,
            # Remove spaces at the start of each (non-commented) line, caused by the indent configuration.
            # This is only needed when the YAML data is a list of items, like in the problems.yaml file.
            # See also: https://stackoverflow.com/a/58773229
            transform=(
                (
                    lambda yaml_str: "\n".join(
                        line if line.strip().startswith("#") else line[2:]
                        for line in yaml_str.split("\n")
                    )
                )
                if isinstance(data, list)
                else None
            ),
        )
        if isinstance(_path, StringIO):
            string = _path.getvalue()
            _path.close()
            return string
    return None


def _ask_variable(name: str, default: Optional[str] = None, allow_empty: bool = False) -> str:
    if config.args.defaults:
        if not default and not allow_empty:
            fatal(f"{name} has no default")
        return default or ""
    while True:
        val = input(f"{name}: ")
        val = val or default or ""
        if val != "" or allow_empty:
            return val


def ask_variable_string(name: str, default: Optional[str] = None, allow_empty: bool = False) -> str:
    if has_questionary:
        try:
            validate = None if allow_empty else EmptyValidator
            return cast(
                str,
                questionary.text(name + ":", default=default or "", validate=validate).unsafe_ask(),
            )
        except KeyboardInterrupt:
            fatal("Running interrupted")
    else:
        text = f" ({default})" if default else ""
        return _ask_variable(name + text, default if default else "", allow_empty)


def ask_variable_bool(name: str, default: bool = True) -> bool:
    if has_questionary:
        try:
            return cast(
                bool,
                questionary.confirm(name + "?", default=default, auto_enter=False).unsafe_ask(),
            )
        except KeyboardInterrupt:
            fatal("Running interrupted")
    else:
        text = " (Y/n)" if default else " (y/N)"
        return _ask_variable(name + text, "Y" if default else "N").lower()[0] == "y"


def ask_variable_choice(name: str, choices: Sequence[str], default: Optional[str] = None) -> str:
    if has_questionary:
        try:
            plain = questionary.Style([("selected", "noreverse")])
            return cast(
                str,
                questionary.select(
                    name + ":", choices=choices, default=default, style=plain
                ).unsafe_ask(),
            )
        except KeyboardInterrupt:
            fatal("Running interrupted")
    else:
        default = default or choices[0]
        text = f" ({default})" if default else ""
        while True:
            got = _ask_variable(name + text, default if default else "")
            if got in choices:
                return got
            else:
                warn(f"unknown option: {got}")


# glob, but without hidden files
def glob(path: Path, expression: str, include_hidden: bool = False) -> list[Path]:
    def keep(p: Path) -> bool:
        if not include_hidden:
            for d in p.parts:
                if d[0] == ".":
                    return False

        if p.suffix in [".template", ".disabled"]:
            return False

        if config.RUNNING_TEST:
            suffixes = p.suffixes
            if len(suffixes) >= 1 and suffixes[-1] == ".bad":
                return False
            if len(suffixes) >= 2 and suffixes[-2] == ".bad":
                return False

        return True

    return sorted(p for p in path.glob(expression) if keep(p))


def strip_newline(s: str) -> str:
    if s.endswith("\n"):
        return s[:-1]
    else:
        return s


# check if windows supports symlinks
if is_windows():
    link_parent = Path(tempfile.gettempdir()) / "bapctools"
    link_dest = link_parent / "dir"
    link_dest.mkdir(parents=True, exist_ok=True)
    link_src = link_parent / "link"
    if link_src.exists() or link_src.is_symlink():
        link_src.unlink()
    try:
        link_src.symlink_to(link_dest, True)
        windows_can_symlink = True
    except OSError:
        windows_can_symlink = False
        warn(
            """Please enable the developer mode in Windows to enable symlinks!
- Open the Windows Settings
- Go to "Update & security"
- Go to "For developers"
- Enable the option "Developer Mode"
"""
        )


# When output is True, copy the file when args.cp is true.
def ensure_symlink(link: Path, target: Path, output: bool = False, relative: bool = False) -> bool:
    try:
        # on windows copy if necessary
        if is_windows() and not windows_can_symlink:
            if link.exists() or link.is_symlink():
                link.unlink()
            shutil.copyfile(target, link)
            return True

        # For output files: copy them on Windows, or when --cp is passed.
        if output and config.args.cp:
            if link.exists() or link.is_symlink():
                link.unlink()
            shutil.copyfile(target, link)
            return True

        # Do nothing if link already points to the right target.
        if link.is_symlink() and link.resolve() == target.resolve():
            is_absolute = os.readlink(link)
            if not relative and is_absolute:
                return True
            # if relative and not is_absolute: return

        if link.is_symlink() or link.exists():
            if link.is_dir() and not link.is_symlink():
                shutil.rmtree(link)
            else:
                link.unlink()

        # for windows the symlink needs to know if it points to a directory or file
        if relative:
            # Rewrite target to be relative to link.
            # Use os.path.relpath instead of Path.relative_to for non-subdirectories.
            link.symlink_to(os.path.relpath(target, link.parent), target.is_dir())
        else:
            link.symlink_to(target.absolute(), target.is_dir())
        return True
    except (FileNotFoundError, FileExistsError):
        # this must be a race condition
        return False


def has_substitute(
    inpath: Path, pattern: re.Pattern[str] = config.BAPCTOOLS_SUBSTITUTE_REGEX
) -> bool:
    try:
        data = inpath.read_text()
    except UnicodeDecodeError:
        return False
    return pattern.search(data) is not None


def substitute(
    data: str,
    variables: Optional[Mapping[str, Optional[object]]],
    *,
    pattern: re.Pattern[str] = config.BAPCTOOLS_SUBSTITUTE_REGEX,
    bar: BAR_TYPE = PrintBar(),
) -> str:
    if variables is None:
        variables = {}

    def substitute_function(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in variables:
            return str(variables[name]) if variables[name] is not None else ""
        else:
            variable = match.group()
            bar.warn(f"Found pattern '{variable}' but no substitution was provided. Skipped.")
            return variable

    return pattern.sub(substitute_function, data)


def copy_and_substitute(
    inpath: Path,
    outpath: Path,
    variables: Optional[Mapping[str, Optional[object]]],
    *,
    pattern: re.Pattern[str] = config.BAPCTOOLS_SUBSTITUTE_REGEX,
    bar: BAR_TYPE = PrintBar(),
) -> None:
    try:
        data = inpath.read_text()
    except UnicodeDecodeError:
        # skip this file
        bar.log(f'File "{inpath}" is not a text file.')
        return
    data = substitute(data, variables, pattern=pattern, bar=bar)
    if outpath.is_symlink():
        outpath.unlink()
    outpath.write_text(data)


def substitute_file_variables(
    path: Path,
    variables: Optional[Mapping[str, Optional[object]]],
    *,
    pattern: re.Pattern[str] = config.BAPCTOOLS_SUBSTITUTE_REGEX,
    bar: BAR_TYPE = PrintBar(),
) -> None:
    copy_and_substitute(path, path, variables, pattern=pattern, bar=bar)


def substitute_dir_variables(
    dirname: Path,
    variables: Optional[Mapping[str, Optional[object]]],
    *,
    pattern: re.Pattern[str] = config.BAPCTOOLS_SUBSTITUTE_REGEX,
    bar: BAR_TYPE = PrintBar(),
) -> None:
    for path in dirname.rglob("*"):
        if path.is_file():
            substitute_file_variables(path, variables, pattern=pattern, bar=bar)


# copies a directory recursively and substitutes {%key%} by their value in text files
# reference: https://docs.python.org/3/library/shutil.html#copytree-example
def copytree_and_substitute(
    src: Path,
    dst: Path,
    variables: Optional[Mapping[str, Optional[object]]],
    exist_ok: bool = True,
    *,
    preserve_symlinks: bool = True,
    base: Optional[Path] = None,
    skip: Optional[Iterable[Path]] = None,
    pattern: re.Pattern[str] = config.BAPCTOOLS_SUBSTITUTE_REGEX,
    bar: BAR_TYPE = PrintBar(),
) -> None:
    if base is None:
        base = src

    if skip and src in skip:
        pass
    elif preserve_symlinks and os.path.islink(src):
        shutil.copy(src, dst, follow_symlinks=False)
    elif os.path.islink(src) and src.absolute().is_relative_to(base.absolute()):
        shutil.copy(src, dst, follow_symlinks=False)
    elif os.path.isdir(src):
        names = os.listdir(src)
        os.makedirs(dst, exist_ok=exist_ok)
        errors = []
        for name in names:
            try:
                srcFile = src / name
                dstFile = dst / name

                copytree_and_substitute(
                    srcFile,
                    dstFile,
                    variables,
                    exist_ok,
                    preserve_symlinks=preserve_symlinks,
                    base=base,
                    skip=skip,
                    pattern=pattern,
                    bar=bar,
                )
            except OSError as why:
                errors.append((srcFile, dstFile, str(why)))
            # catch the Error from the recursive copytree so that we can
            # continue with other files
            except Exception as err:
                errors.append(err.args[0])
        if errors:
            raise Exception(errors)

    elif dst.exists():
        bar.warn(f'File "{dst}" already exists, skipping...')
    else:
        try:
            data = src.read_text()
            data = substitute(data, variables, pattern=pattern, bar=bar)
            dst.write_text(data)
        except UnicodeDecodeError:
            # Do not substitute for binary files.
            dst.write_bytes(src.read_bytes())


# this eval is still dangerous, but on the other hand we run submission code so this is fine
def math_eval(text: str) -> Optional[int | float]:
    # try to guess the meaning of dot and comma (punctuation and separator)
    if text.count(".") != 1 and text.count(",") <= 1:
        text = text.translate(str.maketrans(".,", ",."))
    text.replace(",", "")

    # make math eval slightly safer
    allowed = string.digits + "+-*/()." + "eE" + string.whitespace
    if any(c not in allowed for c in text):
        return None

    try:
        value = eval(text, {"__builtin__": None})
        if isinstance(value, (int, float)):
            return value
    except Exception:
        pass
    return None


def crop_output(output: str) -> str:
    if config.args.error:
        return output

    lines = output.split("\n")
    numlines = len(lines)
    cropped = False
    # Cap number of lines
    if numlines > 30:
        output = "\n".join(lines[:25])
        output += "\n"
        cropped = True

    # Cap total length.
    if len(output) > 2000:
        output = output[:2000]
        output += " ...\n"
        cropped = True

    if cropped:
        output += Fore.YELLOW + "Use -e to show more." + Style.RESET_ALL
    return output


def tail(string: str, limit: int) -> str:
    lines = string.split("\n")
    if len(lines) > limit:
        lines = lines[-limit:]
        lines[0] = f"{Style.DIM}[...]{Style.RESET_ALL}"
    return "\n".join(lines)


class ExecStatus(Enum):
    ACCEPTED = 1
    REJECTED = 2
    ERROR = 3
    TIMEOUT = 4

    def __bool__(self) -> bool:
        return self == ExecStatus.ACCEPTED


class ExecResult:
    def __init__(
        self,
        returncode: Optional[int],
        status: ExecStatus,
        duration: int | float,
        timeout_expired: bool,
        err: Optional[str],
        out: Optional[str],
        verdict: Optional["Verdict"] = None,
        pass_id: Optional[int] = None,
    ) -> None:
        self.returncode = returncode
        self.status = status
        self.duration = duration
        self.timeout_expired = timeout_expired
        self.err = err
        self.out = out
        self.verdict = verdict
        self.pass_id = pass_id


def command_supports_memory_limit(command: Sequence[str | Path]) -> bool:
    # https://bugs.openjdk.org/browse/JDK-8071445
    return Path(command[0]).name not in ["java", "javac", "kotlin", "kotlinc", "sbcl"]


def limit_setter(
    command: Optional[Sequence[str | Path]],
    timeout: Optional[int],
    memory_limit: Optional[int],
    group: Optional[int] = None,
    cores: Literal[False] | list[int] = False,
) -> Callable[[], None]:
    # perform all syscalls / things that could fail in the current context, i.e., outside of the preexec_fn
    disable_stack_limit = not is_bsd()

    if config.args.memory:
        memory_limit = config.args.memory
    if memory_limit:
        memory_limit *= 1024**2
        assert command is not None
        if not command_supports_memory_limit(command):
            memory_limit = None
    if config.args.sanitizer or is_bsd() or is_windows():
        memory_limit = None

    if group is not None:
        assert not is_windows()
        assert not is_mac()

    if is_windows() or is_bsd():
        cores = False

    if disable_stack_limit:
        current = resource.getrlimit(resource.RLIMIT_STACK)
        if current[1] != resource.RLIM_INFINITY:
            fatal("Stacklimit must be unlimited")
    if memory_limit is not None:
        current = resource.getrlimit(resource.RLIMIT_AS)
        if current[1] != resource.RLIM_INFINITY and current[1] < memory_limit:
            fatal(f"Insufficient memory limit: {current[1]}")

    # actual preexec_fn called in the context of the new process
    # this should only do resource and os calls to stay safe
    def setlimits() -> None:
        if timeout is not None:
            resource.setrlimit(resource.RLIMIT_CPU, (timeout + 1, timeout + 1))

        # Increase the max stack size from default to the max available.
        if disable_stack_limit:
            resource.setrlimit(
                resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
            )

        if memory_limit is not None:
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

        if group is not None:
            os.setpgid(0, group)

        if cores is not False:
            os.sched_setaffinity(0, cores)

        # Disable coredumps.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return setlimits


# Subclass Popen to get rusage information.
class ResourcePopen(subprocess.Popen[bytes]):
    rusage: "Optional[resource.struct_rusage]"

    # If wait4 is available, store resource usage information.
    if "wait4" in dir(os):

        def _try_wait(self, wait_flags: int) -> tuple[int, int]:
            """All callers to this function MUST hold self._waitpid_lock."""
            try:
                (pid, sts, res) = os.wait4(self.pid, wait_flags)
            except ChildProcessError:
                # This happens if SIGCLD is set to be ignored or waiting
                # for child processes has otherwise been disabled for our
                # process.  This child is dead, we can't get the status.
                pid = self.pid
                sts = 0
            else:
                self.rusage = res
            return (pid, sts)

    else:

        def _try_wait(self, wait_flags: int) -> tuple[int, int]:
            """All callers to this function MUST hold self._waitpid_lock."""
            try:
                (pid, sts) = os.waitpid(self.pid, wait_flags)
            except ChildProcessError:
                # This happens if SIGCLD is set to be ignored or waiting
                # for child processes has otherwise been disabled for our
                # process.  This child is dead, we can't get the status.
                pid = self.pid
                sts = 0
            else:
                self.rusage = None
            return (pid, sts)


class AbortException(Exception):
    pass


def default_exec_code_map(returncode: int) -> ExecStatus:
    if returncode == 0:
        return ExecStatus.ACCEPTED
    if returncode == -9:
        return ExecStatus.TIMEOUT
    return ExecStatus.ERROR


def validator_exec_code_map(returncode: int) -> ExecStatus:
    if returncode == config.RTV_AC:
        return ExecStatus.ACCEPTED
    if returncode == config.RTV_WA:
        return ExecStatus.REJECTED
    if returncode == -9:
        return ExecStatus.TIMEOUT
    return ExecStatus.ERROR


# Run `command`, returning stderr if the return code is unexpected.
def exec_command(
    command: Sequence[str | Path],
    exec_code_map: Callable[[int], ExecStatus] = default_exec_code_map,
    crop: bool = True,
    preexec_fn: bool = True,
    **kwargs: Any,
) -> ExecResult:
    # By default: discard stdout, return stderr
    if "stdout" not in kwargs or kwargs["stdout"] is True:
        kwargs["stdout"] = subprocess.PIPE
    if "stderr" not in kwargs or kwargs["stderr"] is True:
        kwargs["stderr"] = subprocess.PIPE

    # Convert any Pathlib objects to string.
    command = [str(x) for x in command]

    if config.args.verbose >= 2:
        if "cwd" in kwargs:
            eprint("cd", kwargs["cwd"], "; ", end="")
        else:
            eprint("cd", Path.cwd(), "; ", end="")
        eprint(*command, end="")
        if "stdin" in kwargs:
            eprint(" < ", kwargs["stdin"].name, end="")
        eprint()

    timeout: Optional[int] = None
    if "timeout" in kwargs:
        timeout = kwargs["timeout"]
        kwargs.pop("timeout")

    memory: Optional[int] = None
    if "memory" in kwargs:
        memory = kwargs["memory"]
        kwargs.pop("memory")

    process: Optional[ResourcePopen] = None
    old_handler = None

    def interrupt_handler(sig: Any, frame: Any) -> None:
        nonlocal process
        if process is not None:
            process.kill()
        if callable(old_handler):
            old_handler(sig, frame)

    if threading.current_thread() is threading.main_thread():
        old_handler = signal.signal(signal.SIGINT, interrupt_handler)

    timeout_expired = False
    tstart = time.monotonic()

    try:
        if not is_windows() and preexec_fn is not False:
            process = ResourcePopen(
                command,
                preexec_fn=limit_setter(command, timeout, memory),
                **kwargs,
            )
        else:
            process = ResourcePopen(command, **kwargs)
    except PermissionError as e:
        # File is likely not executable.
        return ExecResult(None, ExecStatus.ERROR, 0, False, str(e), None)
    except OSError as e:
        # File probably doesn't exist.
        return ExecResult(None, ExecStatus.ERROR, 0, False, str(e), None)

    try:
        (stdout, stderr) = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Timeout expired.
        timeout_expired = True
        process.kill()
        (stdout, stderr) = process.communicate()

    tend = time.monotonic()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, old_handler)

    # -2 corresponds to SIGINT, i.e. keyboard interrupt / CTRL-C.
    if process.returncode == -2:
        raise AbortException()

    def maybe_crop(s: str) -> str:
        return crop_output(s) if crop else s

    status = exec_code_map(process.returncode)
    err = maybe_crop(stderr.decode("utf-8", "replace")) if stderr is not None else None
    out = maybe_crop(stdout.decode("utf-8", "replace")) if stdout is not None else None

    if hasattr(process, "rusage") and process.rusage:
        duration = process.rusage.ru_utime + process.rusage.ru_stime
        # It may happen that the Rusage is low, even though a timeout was raised, i.e. when calling sleep().
        # To prevent under-reporting the duration, we take the max with wall time in this case.
        if timeout_expired:
            duration = max(tend - tstart, duration)
    else:
        duration = tend - tstart

    return ExecResult(process.returncode, status, duration, timeout_expired, err, out)


def inc_label(label: str) -> str:
    for x in range(len(label) - 1, -1, -1):
        if label[x] != "Z":
            label = label[:x] + chr(ord(label[x]) + 1) + label[x + 1 :]
            return label
        label = label[:x] + "A" + label[x + 1 :]
    return "A" + label


# A path is a problem directory if it contains a `problem.yaml` file.
def is_problem_directory(path: Path) -> bool:
    return (path / "problem.yaml").is_file()


def combine_hashes(values: Sequence[str]) -> str:
    hasher = hashlib.sha512(usedforsecurity=False)
    for item in sorted(values):
        hasher.update(item.encode())
    return hasher.hexdigest()


def combine_hashes_dict(d: Mapping[str, Optional[str]]) -> str:
    hasher = hashlib.sha512(usedforsecurity=False)
    for key, value in d.items():
        hasher.update(key.encode())
        if value is not None:
            hasher.update(value.encode())
    return hasher.hexdigest()


def hash_string(string: str) -> str:
    sha = hashlib.sha512(usedforsecurity=False)
    sha.update(string.encode())
    return sha.hexdigest()


def hash_file_content(file: Path, buffer_size: int = 65536) -> str:
    if not file.is_file():
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(file))
    sha = hashlib.sha512(usedforsecurity=False)

    with file.open("rb") as f:
        while True:
            data = f.read(buffer_size)
            if not data:
                break
            sha.update(data)

    return sha.hexdigest()


def hash_file(file: Path, buffer_size: int = 65536) -> str:
    if not file.is_file():
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(file))
    sha = hashlib.sha512(usedforsecurity=False)
    name = file.name.encode("utf-8")
    sha.update(len(name).to_bytes(8, "big"))
    sha.update(name)

    with file.open("rb") as f:
        while True:
            data = f.read(buffer_size)
            if not data:
                break
            sha.update(data)

    return sha.hexdigest()


def hash_file_or_dir(file_or_dir: Path, buffer_size: int = 65536) -> str:
    if file_or_dir.is_dir():
        return combine_hashes(
            [hash_string(file_or_dir.name)]
            + [hash_file_or_dir(f, buffer_size=buffer_size) for f in file_or_dir.iterdir()]
        )
    else:
        return hash_file(file_or_dir, buffer_size=buffer_size)


def generate_problem_uuid() -> str:
    uuid_bytes = bytearray(secrets.token_bytes(16))
    # mark this as v8 uuid (custom uuid) variant 0
    uuid_bytes[6] &= 0b0000_1111
    uuid_bytes[6] |= 0b1000_0000
    uuid_bytes[8] &= 0b0011_1111
    # format as uuid
    uuid = uuid_bytes.hex()
    uuid = f"{uuid[0:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:32]}"
    # make the first bytes BAPCtools specific
    uuid = config.BAPC_UUID[: config.BAPC_UUID_PREFIX] + uuid[config.BAPC_UUID_PREFIX :]
    return uuid


def is_uuid(uuid: str) -> bool:
    try:
        return uuid.casefold() == str(UUID(uuid)).casefold()
    except ValueError:
        return False


class ShellCommand:
    @staticmethod
    def get(cmd: str) -> Optional["ShellCommand"]:
        if shutil.which(cmd) is None:
            return None
        return ShellCommand(cmd)

    def __init__(self, cmd: str) -> None:
        self.cmd = cmd

    def __call__(self, *args: str | Path) -> str:
        res = exec_command(
            ["git", *args],
            crop=False,
            preexec_fn=False,
            timeout=None,
        )
        return res.out if res.status == ExecStatus.ACCEPTED and res.out else ""
