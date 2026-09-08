from collections.abc import Callable, Sequence
from typing import Final, Optional, TypeAlias, TypeVar

from bapctools.validate import AnswerValidator, AnyValidator, InputValidator, OutputValidator

ALL_VALIDATORS: Final[Sequence[type[AnyValidator]]] = [
    AnswerValidator,
    InputValidator,
    OutputValidator,
]
IN_ANS_VALIDATORS: Final[Sequence[type[AnyValidator]]] = [InputValidator, AnswerValidator]
INVALID_GENERATOR_TYPE: TypeAlias = tuple[
    str, bytes | Callable[[bytes], Optional[bytes]], Sequence[type[AnyValidator]]
]
VALID_GENERATOR_TYPE: TypeAlias = tuple[str, bytes | Callable[[bytes], Optional[bytes]], bool, bool]
T = TypeVar("T", bound=bytes | Callable[[bytes], Optional[bytes]])


# helper function
def _append_before_newline(text: bytes, token: bytes) -> Optional[bytes]:
    if not text.endswith(b"\n"):
        return None
    return text[:-1] + token + b"\n"


def _list_invalid_generators() -> list[INVALID_GENERATOR_TYPE]:
    generator_names: set[str] = set()
    generators: list[INVALID_GENERATOR_TYPE] = []

    # returns a function that can be called to register a new generator for invalid tests
    # can be used on its own or as decorator for a function
    def register(
        name: Optional[str] = None,
        supported_cls: type[AnyValidator] | Sequence[type[AnyValidator]] = ALL_VALIDATORS,
    ) -> Callable[[T], T]:
        def decorator(func: T) -> T:
            nonlocal name
            nonlocal supported_cls
            if not isinstance(func, bytes) and name is None:
                assert hasattr(func, "__name__")
                name = func.__name__
            assert name
            if not isinstance(supported_cls, Sequence):
                supported_cls = [supported_cls]
            generator_names.add(name)
            generators.append((name, func, supported_cls))
            return func

        return decorator

    # constant test cases
    register("latin-1")("Naïve".encode())
    register("empty", [InputValidator, OutputValidator])(b"")
    register("newline")(b"\n")
    register("fixed_random")(b"YVRtr&*teTsRjs8ZC2%kN*T63V@jJq!d")
    register("not_printable_ascii")(b"\x7f")
    register("not_printable_unicode")(b"\xe2\x82\xac")
    register("unicode")(r"¯\_(ツ)_/¯".encode())
    register("bismillah")("﷽".encode())

    # simple generators
    register("leading_zero", IN_ANS_VALIDATORS)(lambda x: b"0" + x)
    register("leading_space", IN_ANS_VALIDATORS)(lambda x: b" " + x)
    register("leading_plus", IN_ANS_VALIDATORS)(lambda x: b"+" + x)
    register("trailing_token_int")(lambda x: x + b"42\n")
    register("trailing_token_str")(lambda x: x + b"hello\n")
    register("trailing_newline", IN_ANS_VALIDATORS)(lambda x: x + b"\n")
    register("append_token_str")(lambda x: _append_before_newline(x, b" hello"))
    register("append_token_int")(lambda x: _append_before_newline(x, b" 42"))
    register("append_space", IN_ANS_VALIDATORS)(lambda x: _append_before_newline(x, b" "))

    @register(supported_cls=IN_ANS_VALIDATORS)
    def drop_newline(x: bytes) -> Optional[bytes]:
        if not x.endswith(b"\n"):
            return None
        return x[:-1]

    @register(supported_cls=IN_ANS_VALIDATORS)
    def swap_case(x: bytes) -> Optional[bytes]:
        if x.islower() or x.isupper() or x.istitle():
            return x.swapcase()
        return None

    @register(supported_cls=IN_ANS_VALIDATORS)
    def windows_newline(x: bytes) -> Optional[bytes]:
        if b"\n" not in x or b"\r" in x:
            return None
        return x.replace(b"\n", b"\r\n")

    return generators


INVALID_GENERATORS: Final[Sequence[INVALID_GENERATOR_TYPE]] = _list_invalid_generators()
del _list_invalid_generators


def _list_valid_generators() -> list[VALID_GENERATOR_TYPE]:
    generator_names: set[str] = set()
    generators: list[VALID_GENERATOR_TYPE] = []

    # returns a function that can be called to register a new generator for valid tests
    # can be used on its own or as decorator for a function
    def register(
        name: Optional[str] = None, space_change: bool = False, case_change: bool = False
    ) -> Callable[[T], T]:
        def decorator(func: T) -> T:
            nonlocal name
            if not isinstance(func, bytes) and not name:
                assert hasattr(func, "__name__")
                name = func.__name__
            assert name
            generator_names.add(name)
            generators.append((name, func, space_change, case_change))
            return func

        return decorator

    # simple generators
    register("leading_space", space_change=True)(lambda x: b" " + x)
    register("trailing_newline", space_change=True)(lambda x: x + b"\n")
    register("append_space", space_change=True)(lambda x: _append_before_newline(x, b" "))

    @register(space_change=True)
    def all_newline(x: bytes) -> Optional[bytes]:
        if b" " not in x:
            return None
        return x.replace(b" ", b"\n")

    @register(space_change=True)
    def all_space(x: bytes) -> Optional[bytes]:
        if b"\n" not in x:
            return None
        return x.replace(b"\n", b" ")

    @register(space_change=True)
    def drop_newline(x: bytes) -> Optional[bytes]:
        if not x.endswith(b"\n"):
            return None
        return x[:-1]

    @register(space_change=True)
    def windows_newline(x: bytes) -> Optional[bytes]:
        if b"\n" not in x or b"\r" in x:
            return None
        return x.replace(b"\n", b"\r\n")

    @register(case_change=True)
    def swap_case(x: bytes) -> Optional[bytes]:
        y = x.swapcase()
        return None if x == y else y

    return generators


VALID_GENERATORS: Final[Sequence[VALID_GENERATOR_TYPE]] = _list_valid_generators()
del _list_valid_generators
