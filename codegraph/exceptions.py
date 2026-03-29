class CodeGraphError(Exception):
    """Base exception for all codegraph errors."""


class ParseError(CodeGraphError):
    """Raised when a file cannot be parsed."""


class CacheError(CodeGraphError):
    """Raised when cache operations fail."""
