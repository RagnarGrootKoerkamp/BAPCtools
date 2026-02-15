from typing import Optional

from . import VERSION_TYPE as VERSION_TYPE
from .config import Config as Config
from .source_visitor import SourceVisitor as SourceVisitor

def visit(
    source: str, config: Optional[Config] = None, path: Optional[str] = None
) -> SourceVisitor | list[VERSION_TYPE]: ...
