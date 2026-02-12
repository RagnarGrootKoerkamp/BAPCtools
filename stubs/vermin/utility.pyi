from collections.abc import Sequence
from typing import Optional

def dotted_name(
    names: str
    | int
    | float
    | Sequence[Optional[str | int | list[Optional[str]] | tuple[Optional[str], ...]]],
) -> str: ...
