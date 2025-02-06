# read problem settings from config files

import copy
import errno
import hashlib
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from enum import Enum
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn, Optional, TypeVar
from uuid import UUID

import yaml as yamllib
from colorama import Fore, Style
from io import StringIO

import config

try:
    import ruamel.yaml

    has_ryaml = True
    ryaml = ruamel.yaml.YAML(typ="rt")
    ryaml.default_flow_style = False
    ryaml.indent(mapping=2, sequence=4, offset=2)
    ryaml.width = sys.maxsize
except Exception:
    has_ryaml = False


# For some reason ryaml.load doesn't work well in parallel.
ruamel_lock = threading.Lock()


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


def exit1(force=False) -> NoReturn:
    if force:
        sys.stdout.close()
        sys.stderr.close()
        # exit even more forcefully to ensure that daemon threads dont break something
        os._exit(1)
    else:
        sys.exit(1)


def debug(*msg: Any) -> None:
    print(Fore.CYAN, end="", file=sys.stderr)
    print("DEBUG:", *msg, end="", file=sys.stderr)
    print(Style.RESET_ALL, file=sys.stderr)


def log(msg: Any) -> None:
    print(f"{Fore.GREEN}LOG: {msg}{Style.RESET_ALL}", file=sys.stderr)


def verbose(msg: Any) -> None:
    if config.args.verbose >= 1:
        print(f"{Fore.CYAN}VERBOSE: {msg}{Style.RESET_ALL}", file=sys.stderr)


def warn(msg: Any) -> None:
    print(f"{Fore.YELLOW}WARNING: {msg}{Style.RESET_ALL}", file=sys.stderr)
    config.n_warn += 1


def error(msg: Any) -> None:
    if config.RUNNING_TEST:
        fatal(msg)
    print(f"{Fore.RED}ERROR: {msg}{Style.RESET_ALL}", file=sys.stderr)
    config.n_error += 1


def fatal(msg: Any, *, force=threading.active_count() > 1) -> NoReturn:
    print(f"\n{Fore.RED}FATAL ERROR: {msg}{Style.RESET_ALL}", file=sys.stderr)
    exit1(force)


class MessageType(Enum):
    LOG = 1
    WARN = 2
    ERROR = 3
    FATAL = 4

    def __str__(self):
        return {
            MessageType.LOG: str(Fore.GREEN),
            MessageType.WARN: str(Fore.YELLOW),
            MessageType.ERROR: str(Fore.RED),
            MessageType.FATAL: str(Fore.RED),
        }[self]


def message(msg, task=None, item=None, *, color_type=""):
    if task is not None:
        print(f"{Fore.CYAN}{task}{Style.RESET_ALL}: ", end="", file=sys.stderr)
    if item is not None:
        print(item, end="   ", file=sys.stderr)
    print(f"{color_type}{msg}{Style.RESET_ALL}", file=sys.stderr)
    if color_type == MessageType.WARN:
        config.n_warn += 1
    if color_type == MessageType.ERROR:
        config.n_error += 1
    if color_type == MessageType.FATAL:
        exit1()


# A simple bar that only holds a task prefix
class PrintBar:
    def __init__(self, task):
        self.task = task

    def log(self, msg, item=None):
        message(msg, self.task, item, color_type=MessageType.LOG)

    def warn(self, msg, item=None):
        message(msg, self.task, item, color_type=MessageType.WARN)

    def error(self, msg, item=None):
        message(msg, self.task, item, color_type=MessageType.ERROR)

    def fatal(self, msg, item=None):
        message(msg, self.task, item, color_type=MessageType.FATAL)


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

        def update_columns(_: Any, __: Any):
            cols, rows = shutil.get_terminal_size()
            ProgressBar.columns = cols

        signal.signal(signal.SIGWINCH, update_columns)

    @staticmethod
    def item_len(item):
        if isinstance(item, str):
            return len(item)
        if isinstance(item, Path):
            return len(str(item))
        return len(item.name)

    def _is_locked(self):
        return ProgressBar.lock_depth > 0

    # When needs_leading_newline is True, this will print an additional empty line before the first log message.
    def __init__(
        self,
        prefix,
        max_len=None,
        count=None,
        *,
        items=None,
        needs_leading_newline=False,
    ):
        assert ProgressBar.current_bar is None, ProgressBar.current_bar.prefix  # type: ignore[has-type]
        ProgressBar.current_bar = self

        assert not (items and (max_len or count))
        assert items is not None or max_len
        if items is not None:
            count = len(items)
            if count == 0:
                max_len = 0
            else:
                max_len = max(ProgressBar.item_len(x) for x in items)
        self.prefix = prefix  # The prefix to always print
        self.item_width = max_len + 1  # The max length of the items we're processing
        self.count = count  # The number of items we're processing
        self.i = 0
        emptyline = " " * self.total_width() + "\r"
        self.carriage_return = emptyline if is_windows() else "\033[K"
        self.logged = False
        self.global_logged = False

        # For parallel contexts, start() will return a copy to preserve the item name.
        # The parent still holds some global state:
        # - global_logged
        # - IO lock
        # - the counter
        # - items in progress
        self.parent = None
        self.in_progress = set()
        self.item = None

        self.needs_leading_newline = needs_leading_newline

    def __enter__(self):
        ProgressBar.lock.__enter__()
        ProgressBar.lock_depth += 1

    def __exit__(self, *args):
        ProgressBar.lock_depth -= 1
        ProgressBar.lock.__exit__(*args)

    def _print(self, *objects, sep="", end="\n", file=sys.stderr, flush=True):
        print(*objects, sep=sep, end=end, file=file, flush=flush)

    def total_width(self):
        cols = ProgressBar.columns
        if is_windows():
            cols -= 1
        return cols

    def bar_width(self):
        if self.item_width is None:
            return None
        return self.total_width() - len(self.prefix) - 2 - self.item_width

    def update(self, count, max_len):
        self.count += count
        self.item_width = max(self.item_width, max_len + 1) if self.item_width else max_len + 1

    def add_item(self, item):
        self.count += 1
        self.item_width = max(self.item_width, ProgressBar.item_len(item))

    def clearline(self):
        if config.args.no_bar:
            return
        assert self._is_locked()
        self._print(self.carriage_return, end="", flush=False)

    @staticmethod
    def action(prefix, item, width=None, total_width=None, print_item=True):
        if width is not None and total_width is not None and len(prefix) + 2 + width > total_width:
            width = total_width - len(prefix) - 2
        item = "" if item is None else (item if isinstance(item, str) else item.name)
        if width is not None and len(item) > width:
            item = item[:width]
        if width is None or width <= 0:
            width = 0
        if print_item:
            return f"{Fore.CYAN}{prefix}{Style.RESET_ALL}: {item:<{width}}"
        else:
            return f"{Fore.CYAN}{prefix}{Style.RESET_ALL}: {' ' * width}"

    def get_prefix(self, print_item=True):
        return ProgressBar.action(
            self.prefix, self.item, self.item_width, self.total_width(), print_item
        )

    def get_bar(self):
        bar_width = self.bar_width()
        if self.count is None or bar_width < 4:
            return ""
        done = (self.i - 1) * (bar_width - 2) // self.count
        text = f" {self.i}/{self.count}"
        fill = "#" * done + "-" * (bar_width - 2 - done)
        if len(text) <= len(fill):
            fill = fill[: -len(text)] + text
        return "[" + fill + "]"

    def draw_bar(self):
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
    def _release_item(self):
        if self.parent:
            self.parent.in_progress.remove(self.item)
            if self.parent.item is self.item:
                self.parent.item = None
        else:
            self.in_progress.remove(self.item)
        self.item = None

    # Resume the ongoing progress bar after a log/done.
    # Should only be called for the root.
    def _resume(self):
        assert self._is_locked()
        assert self.parent is None

        if config.args.no_bar:
            return

        if len(self.in_progress) > 0:
            if self.item not in self.in_progress:
                self.item = next(iter(self.in_progress))
            self.draw_bar()

    def start(self, item=""):
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
    def _format_data(data):
        if not data:
            return ""
        prefix = "  " if data.count("\n") <= 1 else "\n"
        return prefix + Fore.YELLOW + strip_newline(crop_output(data)) + Style.RESET_ALL

    # Log can be called multiple times to make multiple persistent lines.
    # Make sure that the message does not end in a newline.
    def log(self, message="", data="", color=Fore.GREEN, *, resume=True, print_item=True):
        with self:
            if message is None:
                message = ""
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
    def debug(self, message, data="", color=Fore.GREEN, *, resume=True, print_item=True):
        if config.args.verbose:
            self.log(message, data, color=color, resume=resume, print_item=print_item)

    def warn(self, message="", data="", *, print_item=True):
        with self.lock:
            config.n_warn += 1
            self.log(message, data, Fore.YELLOW, print_item=print_item)

    # Error by default removes the current item from the in_progress set.
    # Set `resume` to `True` to continue processing the item.
    def error(self, message="", data="", resume=False, print_item=True):
        with self:
            config.n_error += 1
            self.log(message, data, Fore.RED, resume=resume, print_item=print_item)
            if not resume:
                self._release_item()

    # Skip an item.
    def skip(self):
        with self:
            self.i += 1

    # Log a final line if it's an error or if nothing was printed yet and we're in verbose mode.
    def done(self, success=True, message="", data="", print_item=True):
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
    def part_done(self, success=True, message="", data="", warn_instead_of_error=False):
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
    def finalize(self, *, print_done=True, message=None, suppress_newline=False):
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


# Given a command line argument, return the first match:
# - absolute
# - relative to the 'type' directory for the current problem
# - relative to the problem directory
# - relative to the contest directory
# - relative to the current working directory
#
# Pass suffixes = ['.in'] to also try to find the file with the given suffix appended.
def get_basedirs(problem, type):
    p = problem.path
    return [p / type, p, p.parent, config.current_working_directory]


# Python 3.9
# True when child is a Path inside parent Path.
# Both must be absolute.
def is_relative_to(parent, child):
    return child == parent or parent in child.parents


def resolve_path_argument(problem, path, type, suffixes=[]):
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
def shorten_path(problem, path):
    if not path.resolve().is_relative_to(problem.tmpdir):
        return path
    short_hash = hashlib.sha256(bytes(path)).hexdigest()[-6:]
    dir = problem.tmpdir / "links"
    dir.mkdir(parents=True, exist_ok=True)
    short_path = dir / short_hash
    ensure_symlink(short_path, path)
    return short_path


def path_size(path):
    if path.is_file():
        return path.stat().st_size
    else:
        return sum(f.stat().st_size for f in path.rglob("*") if f.exists())


# Drops the first two path components <problem>/<type>/
def print_name(path: Path, keep_type=False) -> str:
    return str(Path(*path.parts[1 if keep_type else 2 :]))


def parse_yaml(data, path=None, plain=False):
    # First try parsing with ruamel.yaml.
    # If not found, use the normal yaml lib instead.
    if has_ryaml and not plain:
        with ruamel_lock:
            try:
                ret = ryaml.load(data)
            except ruamel.yaml.constructor.DuplicateKeyError as error:
                if path is not None:
                    fatal(f"Duplicate key in yaml file {path}!\n{error.args[0]}\n{error.args[2]}")
                else:
                    fatal(f"Duplicate key in yaml object!\n{str(error)}")
        return ret

    else:
        try:
            import yaml

            return yaml.safe_load(data)
        except Exception as e:
            print(f"{Fore.YELLOW}{e}{Style.RESET_ALL}", end="", file=sys.stderr)
            fatal(f"Failed to parse {path}.")


def read_yaml(path, plain=False):
    assert path.is_file(), f"File {path} does not exist"
    return parse_yaml(path.read_text(), path=path, plain=plain)


# Wrapper around read_yaml that returns an empty dictionary by default.
def read_yaml_settings(path):
    settings = {}
    if path.is_file():
        config = read_yaml(path)
        if config is None:
            return None
        if isinstance(config, list):
            return config
        for key, value in config.items():
            settings[key] = "" if value is None else value
    return settings


# Only allow one thread to write at the same time. Else, e.g., generating test cases in parallel goes wrong.
write_yaml_lock = threading.Lock()


# Writing a yaml file (or return as string) only works when ruamel.yaml is loaded. Check if `has_ryaml` is True before using.
def write_yaml(data, path=None, allow_yamllib=False):
    if not has_ryaml:
        if not allow_yamllib:
            error(
                "This operation requires the ruamel.yaml python3 library. Install python[3]-ruamel.yaml."
            )
            exit(1)
        if path is None:
            return yamllib.dump(data)
        with open(path, "w") as stream:
            yamllib.dump(data, stream)
        return
    with write_yaml_lock:
        return_string = False
        if path is None:
            path = StringIO()
            return_string = True
        ryaml.dump(
            data,
            path,
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
        if return_string:
            string = path.getvalue()
            path.close()
            return string


T = TypeVar("T")


def parse_optional_setting(yamldata: dict[str, Any], key: str, t: type[T]) -> Optional[T]:
    if key in yamldata:
        value = yamldata.pop(key)
        if isinstance(value, int) and t is float:
            value = float(value)
        if isinstance(value, t):
            return value
        if value == "" and t in [list, dict]:
            # handle empty yaml keys
            return t()
        else:
            warn(f"incompatible value for key '{key}' in problem.yaml. SKIPPED.")
    return None


def parse_setting(yamldata: dict[str, Any], key: str, default: T) -> T:
    value = parse_optional_setting(yamldata, key, type(default))
    return default if value is None else value


# Parse validation mode
def parse_validation(mode: str) -> set[str]:
    if mode == "default":
        return {mode}
    else:
        ok = True
        parsed = set()
        for part in mode.split():
            if part in ["custom", "interactive", "multi-pass"] and part not in parsed:
                parsed.add(part)
            else:
                ok = False
        if "custom" not in parsed or not ok:
            fatal(f"Unrecognised validation mode {mode}.")
        return parsed


# glob, but without hidden files
def glob(path: Path, expression: str, include_hidden=False) -> list[Path]:
    def keep(p: Path):
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
def ensure_symlink(link, target, output=False, relative=False):
    # on windows copy if necessary
    if is_windows() and not windows_can_symlink:
        if link.exists() or link.is_symlink():
            link.unlink()
        shutil.copyfile(target, link)
        return

    # For output files: copy them on Windows, or when --cp is passed.
    if output and config.args.cp:
        if link.exists() or link.is_symlink():
            link.unlink()
        shutil.copyfile(target, link)
        return

    # Do nothing if link already points to the right target.
    if link.is_symlink() and link.resolve() == target.resolve():
        is_absolute = os.readlink(link)
        if not relative and is_absolute:
            return
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
        link.symlink_to(target.resolve(), target.is_dir())


def substitute(data, variables):
    if variables is None:
        return data
    for key in variables:
        r = ""
        if variables[key] is not None:
            r = variables[key]
        data = data.replace("{%" + key + "%}", str(r))
    return data


def copy_and_substitute(inpath, outpath, variables):
    try:
        data = inpath.read_text()
    except UnicodeDecodeError:
        # skip this file
        log(f'File "{inpath}" is not a text file.')
        return
    data = substitute(data, variables)
    if outpath.is_symlink():
        outpath.unlink()
    outpath.write_text(data)


def substitute_file_variables(path, variables):
    copy_and_substitute(path, path, variables)


def substitute_dir_variables(dirname, variables):
    for path in dirname.rglob("*"):
        if path.is_file():
            substitute_file_variables(path, variables)


# copies a directory recursively and substitutes {%key%} by their value in text files
# reference: https://docs.python.org/3/library/shutil.html#copytree-example
def copytree_and_substitute(
    src, dst, variables, exist_ok=True, *, preserve_symlinks=True, base=None, skip=None
):
    if base is None:
        base = src

    if skip and src in skip:
        pass
    elif preserve_symlinks and os.path.islink(src):
        shutil.copy(src, dst, follow_symlinks=False)
    elif os.path.islink(src) and src.resolve().is_relative_to(base):
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
        warn(f'File "{dst}" already exists, skipping...')
    else:
        try:
            data = src.read_text()
            data = substitute(data, variables)
            dst.write_text(data)
        except UnicodeDecodeError:
            # Do not substitute for binary files.
            dst.write_bytes(src.read_bytes())


def crop_output(output):
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


def tail(string, limit):
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

    def __bool__(self):
        return self == ExecStatus.ACCEPTED


class ExecResult:
    def __init__(
        self,
        returncode,
        status,
        duration,
        timeout_expired,
        err,
        out,
        verdict=None,
        pass_id=None,
    ):
        self.returncode = returncode
        assert type(status) is ExecStatus
        self.status = status
        self.duration = duration
        self.timeout_expired = timeout_expired
        self.err = err
        self.out = out
        self.verdict = verdict
        self.pass_id = pass_id


def limit_setter(command, timeout, memory_limit, group=None, cores=False):
    def setlimits():
        if timeout:
            resource.setrlimit(resource.RLIMIT_CPU, (timeout + 1, timeout + 1))

        # Increase the max stack size from default to the max available.
        if not is_bsd():
            resource.setrlimit(
                resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
            )

        if (
            memory_limit
            and Path(command[0]).name not in ["java", "javac", "kotlin", "kotlinc"]
            and not is_bsd()
        ):
            resource.setrlimit(
                resource.RLIMIT_AS,
                (memory_limit * 1024 * 1024, memory_limit * 1024 * 1024),
            )

        # TODO: with python 3.11 it is better to use Popen(process_group=group)
        if group is not None:
            assert not is_windows()
            assert not is_mac()
            os.setpgid(0, group)

        if cores is not False and not is_windows() and not is_bsd():
            os.sched_setaffinity(0, cores)

        # Disable coredumps.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return setlimits


# Subclass Popen to get rusage information.
class ResourcePopen(subprocess.Popen):
    rusage: Any  # TODO #102: use stricter type than `Any`

    # If wait4 is available, store resource usage information.
    if "wait4" in dir(os):

        def _try_wait(self, wait_flags):
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

        def _try_wait(self, wait_flags):
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


def default_exec_code_map(returncode):
    if returncode == 0:
        return ExecStatus.ACCEPTED
    if returncode == -9:
        return ExecStatus.TIMEOUT
    return ExecStatus.ERROR


def validator_exec_code_map(returncode):
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
    exec_code_map=default_exec_code_map,
    crop=True,
    preexec_fn=True,
    **kwargs,
):
    # By default: discard stdout, return stderr
    if "stdout" not in kwargs or kwargs["stdout"] is True:
        kwargs["stdout"] = subprocess.PIPE
    if "stderr" not in kwargs or kwargs["stderr"] is True:
        kwargs["stderr"] = subprocess.PIPE

    # Convert any Pathlib objects to string.
    command = [str(x) for x in command]

    if config.args.verbose >= 2:
        if "cwd" in kwargs:
            print("cd", kwargs["cwd"], "; ", end="", file=sys.stderr)
        else:
            print("cd", Path.cwd(), "; ", end="", file=sys.stderr)
        print(*command, end="", file=sys.stderr)
        if "stdin" in kwargs:
            print(" < ", kwargs["stdin"].name, end="", file=sys.stderr)
        print(file=sys.stderr)

    timeout: Optional[int] = None
    if "timeout" in kwargs:
        if kwargs["timeout"] is None:
            timeout = None
        elif kwargs["timeout"]:
            timeout = kwargs["timeout"]
        kwargs.pop("timeout")

    memory: Optional[int] = None
    if "memory" in kwargs:
        if kwargs["memory"] is not None:
            memory = kwargs["memory"]
        kwargs.pop("memory")
    if config.args.memory:
        memory = config.args.memory
    if is_windows() or config.args.sanitizer:
        memory = None

    process: Optional[ResourcePopen] = None

    def interrupt_handler(sig, frame):
        nonlocal process
        if process is not None:
            process.kill()
        fatal("Running interrupted", force=True)

    if threading.current_thread() is threading.main_thread():
        old_handler = signal.signal(signal.SIGINT, interrupt_handler)

    timeout_expired = False
    tstart = time.monotonic()

    try:
        if not is_windows() and preexec_fn:
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
        if threading.current_thread() is threading.main_thread():
            fatal("Running interrupted")
        else:
            raise ChildProcessError()

    def maybe_crop(s):
        return crop_output(s) if crop else s

    ok = exec_code_map(process.returncode)
    err = maybe_crop(stderr.decode("utf-8", "replace")) if stderr is not None else None
    out = maybe_crop(stdout.decode("utf-8", "replace")) if stdout is not None else None

    if hasattr(process, "rusage"):
        duration = process.rusage.ru_utime + process.rusage.ru_stime
        # It may happen that the Rusage is low, even though a timeout was raised, i.e. when calling sleep().
        # To prevent under-reporting the duration, we take the max with wall time in this case.
        if timeout_expired:
            duration = max(tend - tstart, duration)
    else:
        duration = tend - tstart

    return ExecResult(process.returncode, ok, duration, timeout_expired, err, out)


def inc_label(label):
    for x in range(len(label) - 1, -1, -1):
        if label[x] != "Z":
            label = label[:x] + chr(ord(label[x]) + 1) + label[x + 1 :]
            return label
        label = label[:x] + "A" + label[x + 1 :]
    return "A" + label


def combine_hashes(values):
    values.sort()
    hasher = hashlib.sha512(usedforsecurity=False)
    for item in values:
        hasher.update(item.encode())
    return hasher.hexdigest()


def combine_hashes_dict(d):
    hasher = hashlib.sha512(usedforsecurity=False)
    for key in d:
        hasher.update(key.encode())
        if d[key] is not None:
            hasher.update(d[key].encode())
    return hasher.hexdigest()


def hash_string(string):
    sha = hashlib.sha512(usedforsecurity=False)
    sha.update(string.encode())
    return sha.hexdigest()


def hash_file_content(file, buffer_size=65536):
    if not file.is_file():
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(file))
    sha = hashlib.sha512(usedforsecurity=False)

    with open(file, "rb") as f:
        while True:
            data = f.read(buffer_size)
            if not data:
                break
            sha.update(data)

    return sha.hexdigest()


def hash_file(file, buffer_size=65536):
    if not file.is_file():
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(file))
    sha = hashlib.sha512(usedforsecurity=False)
    name = file.name.encode("utf-8")
    sha.update(len(name).to_bytes(8, "big"))
    sha.update(name)

    with open(file, "rb") as f:
        while True:
            data = f.read(buffer_size)
            if not data:
                break
            sha.update(data)

    return sha.hexdigest()


def hash_file_or_dir(file_or_dir, buffer_size=65536):
    if file_or_dir.is_dir():
        return combine_hashes(
            [hash_string(file_or_dir.name)] + [hash_file_or_dir(f) for f in file_or_dir.iterdir()]
        )
    else:
        return hash_file(file_or_dir)


def generate_problem_uuid():
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


def is_uuid(uuid: str):
    try:
        return uuid.casefold() == str(UUID(uuid)).casefold()
    except ValueError:
        return False
