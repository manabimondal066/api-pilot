"""Parser exception classes."""


class ParserError(Exception):
    """Raised when a spec file cannot be parsed.

    Attributes:
        location: Optional hint about *where* in the spec parsing failed
                  (e.g. a JSON Pointer or a path/method string).
    """

    def __init__(self, message: str, location: str | None = None) -> None:
        self.location = location
        super().__init__(message)
