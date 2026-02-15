import ast

from . import VERSION_TYPE as VERSION_TYPE

class SourceVisitor(ast.NodeVisitor):
    def minimum_versions(self) -> list[VERSION_TYPE]: ...
    def output_text(self) -> str: ...
