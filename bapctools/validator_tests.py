from collections.abc import Callable, Sequence
from typing import Final, Optional, TypeVar

from bapctools.validate import AnswerValidator, AnyValidator, InputValidator, OutputValidator

ALL_VALIDATORS: Final[Sequence[type[AnyValidator]]] = [
    AnswerValidator,
    InputValidator,
    OutputValidator,
]
IN_ANS_VALIDATORS: Final[Sequence[type[AnyValidator]]] = [InputValidator, AnswerValidator]
INVALID_GENERATOR_TYPE = tuple[
    str, bytes | Callable[[bytes], Optional[bytes]], Sequence[type[AnyValidator]]
]
VALID_GENERATOR_TYPE = tuple[str, bytes | Callable[[bytes], Optional[bytes]], bool, bool]
BAD_OUTPUTS_TYPE = tuple[str, bytes, bool]
T = TypeVar("T", bound=bytes | Callable[[bytes], Optional[bytes]])


# helper function
def _append_before_newline(text: bytes, token: bytes) -> Optional[bytes]:
    if not text.endswith(b"\n"):
        return None
    return text[:-1] + token + b"\n"


def _list_invalid_generators() -> Sequence[INVALID_GENERATOR_TYPE]:
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
            assert name not in generator_names
            if not isinstance(supported_cls, Sequence):
                supported_cls = [supported_cls]
            generator_names.add(name)
            generators.append((name, func, supported_cls))
            return func

        return decorator

    # constant test cases
    register("latin-1")("Naïve\n".encode())
    register("1_latin-1")("1\nNaïve\n".encode())
    register("empty", [InputValidator, OutputValidator])(b"")
    register("newline")(b"\n")
    register("fixed_random")(b"YVRtr&*teTsRjs8ZC2%kN*T63V@jJq!d\n")
    register("1_fixed_random")(b"1\nYVRtr&*teTsRjs8ZC2%kN*T63V@jJq!d\n")
    register("not_printable_ascii")(b"\x7f\n")
    register("1_not_printable_ascii")(b"1\n\x7f\n")
    register("not_printable_unicode")(b"\xe2\x82\xac\n")
    register("1_not_printable_unicode")(b"1\n\xe2\x82\xac\n")
    register("unicode")("¯\\_(ツ)_/¯\n".encode())
    register("1_unicode")("1\n¯\\_(ツ)_/¯\n".encode())
    register("bismillah")("﷽\n".encode())
    register("1_bismillah")("1\n﷽\n".encode())

    # simple generators
    register("leading_zero", IN_ANS_VALIDATORS)(lambda x: b"0" + x)
    register("leading_space", IN_ANS_VALIDATORS)(lambda x: b" " + x)
    register("leading_plus", IN_ANS_VALIDATORS)(lambda x: b"+" + x)
    register("trailing_token_int")(lambda x: x + b"42\n")
    register("trailing_token_str")(lambda x: x + b"hello\n")
    register("trailing_newline", IN_ANS_VALIDATORS)(lambda x: x + b"\n")
    register("append_token_str")(lambda x: _append_before_newline(x, b" hello"))
    register("append_token_int")(lambda x: _append_before_newline(x, b" 42"))
    register("append_0byte")(lambda x: _append_before_newline(x, b"\0"))
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

    return tuple(generators)


INVALID_GENERATORS: Final[Sequence[INVALID_GENERATOR_TYPE]] = _list_invalid_generators()
del _list_invalid_generators


def _list_valid_generators() -> Sequence[VALID_GENERATOR_TYPE]:
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
            assert name not in generator_names
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

    return tuple(generators)


VALID_GENERATORS: Final[Sequence[VALID_GENERATOR_TYPE]] = _list_valid_generators()
del _list_valid_generators


def _list_bad_outputs() -> Sequence[BAD_OUTPUTS_TYPE]:
    bad_names: set[str] = set()
    bad_outputs: list[BAD_OUTPUTS_TYPE] = []

    # add invalid bad outputs
    for name, data, supported_cls in INVALID_GENERATORS:
        if OutputValidator not in supported_cls:
            continue
        if not isinstance(data, bytes):
            continue
        bad_names.add(name)
        bad_outputs.append((name, data, False))

    # add possible valid bad outputs
    def register(name: str, data: Optional[bytes] = None) -> None:
        if data is None:
            data = name.encode()
        bad_outputs.append((name, data + b"\n", True))
        bad_outputs.append((f"1_{name}", b"1\n" + data + b"\n", True))

    # integers
    register("0")
    register("-1")
    register("2^31-1", str(2**31 - 1).encode())
    register("2^31", str(2**31).encode())
    register("2^63-1", str(2**63 - 1).encode())
    register("2^63", str(2**63).encode())
    register("10^400", b"1" + b"0" * 400)
    register("10^5000", b"1" + b"0" * 5000)

    # strings
    register("a")
    register("A")
    register("-")
    register("(()")
    register("())")
    register(")(")

    # floats
    register("1.0")
    register("1e309")
    register("1e-400")
    register("NaN")
    register("inf")

    return tuple(bad_outputs)


BAD_OUTPUTS: Final[Sequence[BAD_OUTPUTS_TYPE]] = _list_bad_outputs()
del _list_bad_outputs
