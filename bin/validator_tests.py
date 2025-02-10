from collections.abc import Callable
from typing import Optional, TypeVar

_known_names: set[str] = set()
known: list[tuple[str, str | Callable[[str], Optional[str]], bool]] = []


def generators():
    return known


T = TypeVar("T", bound=str | Callable[[str], Optional[str]])


def register(name: Optional[str] = None, only_whitespace_change: bool = False) -> Callable[[T], T]:
    def decorator(func: T) -> T:
        nonlocal name
        if not isinstance(func, str) and not name:
            assert hasattr(func, "__name__")
            name = func.__name__
        assert name
        _known_names.add(name)
        known.append((name, func, only_whitespace_change))
        return func

    return decorator


# constant testcases
register("latin-1")("Naïve")
register("empty")("")
register("newline")("\n")
register("fixed_random")("YVRtr&*teTsRjs8ZC2%kN*T63V@jJq!d")
register("not_printable_ascii")("\x7f")
register("not_printable_unicode")("\xe2\x82\xac")
register("unicode")("¯\\_(ツ)_/¯")
register("bismillah")("﷽")

# simple generators
register("leading_zero")(lambda x: f"0{x}")
register("leading_space", True)(lambda x: f" {x}")
register("trailing_token_int")(lambda x: f"{x}42\n")
register("trailing_token_str")(lambda x: f"{x}hello\n")
register("trailing_newline", True)(lambda x: f"{x}\n")


# helper function
def end_newline(x: str):
    return len(x) > 0 and x[-1] == "\n"


@register()
def append_token_str(x: str) -> Optional[str]:
    if end_newline(x):
        return None
    return f"{x[:-1]} hello\n"


@register()
def append_token_int(x: str) -> Optional[str]:
    if end_newline(x):
        return None
    return f"{x[:-1]} 42\n"


@register(only_whitespace_change=True)
def append_space(x: str) -> Optional[str]:
    if end_newline(x):
        return None
    return f"{x[:-1]} \n"
