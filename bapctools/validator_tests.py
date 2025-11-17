from collections.abc import Callable, Sequence
from typing import Final, Optional, TypeVar

from bapctools.validate import AnswerValidator, AnyValidator, InputValidator, OutputValidator


# helper function
def end_newline(x: str) -> bool:
    return len(x) > 0 and x[-1] == "\n"


ALL_VALIDATORS: Final[Sequence[type[AnyValidator]]] = [
    AnswerValidator,
    InputValidator,
    OutputValidator,
]
IN_ANS_VALIDATORS: Final[Sequence[type[AnyValidator]]] = [InputValidator, AnswerValidator]


def _list_invalid_generators() -> list[
    tuple[str, str | Callable[[str], Optional[str]], Sequence[type[AnyValidator]]]
]:
    generator_names: set[str] = set()
    generators: list[
        tuple[str, str | Callable[[str], Optional[str]], Sequence[type[AnyValidator]]]
    ] = []

    T = TypeVar("T", bound=str | Callable[[str], Optional[str]])

    # returns a function that can be called to register a new generator for invalid tests
    # can be used on its own or as decorator for a function
    def register(
        name: Optional[str] = None,
        supported_cls: type[AnyValidator] | Sequence[type[AnyValidator]] = ALL_VALIDATORS,
    ) -> Callable[[T], T]:
        def decorator(func: T) -> T:
            nonlocal name
            nonlocal supported_cls
            if not isinstance(func, str) and not name:
                assert hasattr(func, "__name__")
                name = func.__name__
            assert name
            if not isinstance(supported_cls, Sequence):
                supported_cls = [supported_cls]
            generator_names.add(name)
            generators.append((name, func, supported_cls))
            return func

        return decorator

    # constant testcases
    register("latin-1")("Naïve")
    register("empty", [InputValidator, OutputValidator])("")
    register("newline")("\n")
    register("fixed_random")("YVRtr&*teTsRjs8ZC2%kN*T63V@jJq!d")
    register("not_printable_ascii")("\x7f")
    register("not_printable_unicode")("\xe2\x82\xac")
    register("unicode")("¯\\_(ツ)_/¯")
    register("bismillah")("﷽")

    # simple generators
    register("leading_zero", IN_ANS_VALIDATORS)(lambda x: f"0{x}")
    register("leading_space", IN_ANS_VALIDATORS)(lambda x: f" {x}")
    register("leading_plus", IN_ANS_VALIDATORS)(lambda x: f"+{x}")
    register("trailing_token_int")(lambda x: f"{x}42\n")
    register("trailing_token_str")(lambda x: f"{x}hello\n")
    register("trailing_newline", IN_ANS_VALIDATORS)(lambda x: f"{x}\n")

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

    @register(supported_cls=IN_ANS_VALIDATORS)
    def append_space(x: str) -> Optional[str]:
        if end_newline(x):
            return None
        return f"{x[:-1]} \n"

    @register(supported_cls=IN_ANS_VALIDATORS)
    def swap_case(x: str) -> Optional[str]:
        if x.islower() or x.isupper() or x.istitle():
            return x.swapcase()
        return None

    @register(supported_cls=IN_ANS_VALIDATORS)
    def windows_newline(x: str) -> Optional[str]:
        if "\n" not in x or "\r" in x:
            return None
        return x.replace("\n", "\r\n")

    return generators


INVALID_GENERATORS: Final[
    Sequence[tuple[str, str | Callable[[str], Optional[str]], Sequence[type[AnyValidator]]]]
] = _list_invalid_generators()


def _list_valid_generators() -> list[tuple[str, str | Callable[[str], Optional[str]], bool, bool]]:
    generator_names: set[str] = set()
    generators: list[tuple[str, str | Callable[[str], Optional[str]], bool, bool]] = []

    T = TypeVar("T", bound=str | Callable[[str], Optional[str]])

    # returns a function that can be called to register a new generator for valid tests
    # can be used on its own or as decorator for a function
    def register(
        name: Optional[str] = None, space_change: bool = False, case_change: bool = False
    ) -> Callable[[T], T]:
        def decorator(func: T) -> T:
            nonlocal name
            if not isinstance(func, str) and not name:
                assert hasattr(func, "__name__")
                name = func.__name__
            assert name
            generator_names.add(name)
            generators.append((name, func, space_change, case_change))
            return func

        return decorator

    # simple generators
    register("leading_space", space_change=True)(lambda x: f" {x}")
    register("trailing_newline", space_change=True)(lambda x: f"{x}\n")

    @register(space_change=True)
    def all_newline(x: str) -> Optional[str]:
        if " " not in x:
            return None
        return x.replace(" ", "\n")

    @register(space_change=True)
    def all_space(x: str) -> Optional[str]:
        if "\n" not in x:
            return None
        return x.replace("\n", " ")

    @register(space_change=True)
    def append_space(x: str) -> Optional[str]:
        if end_newline(x):
            return None
        return f"{x[:-1]} \n"

    @register(space_change=True)
    def windows_newline(x: str) -> Optional[str]:
        if "\n" not in x or "\r" in x:
            return None
        return x.replace("\n", "\r\n")

    @register(case_change=True)
    def swap_case(x: str) -> Optional[str]:
        y = x.swapcase()
        return None if x == y else y

    return generators


VALID_GENERATORS: Final[Sequence[tuple[str, str | Callable[[str], Optional[str]], bool, bool]]] = (
    _list_valid_generators()
)
