from typing import Literal, Optional

from .config import Config as Config
from .detection import visit as visit
from .source_visitor import SourceVisitor as SourceVisitor
from .utility import dotted_name as dotted_name

__all__ = ["Config", "SourceVisitor", "visit", "dotted_name"]

VERSION_TYPE = Optional[Literal[0] | tuple[int, int]]
