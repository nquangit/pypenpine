"""Exception hierarchy for penpine."""

from __future__ import annotations


class PenpineError(Exception):
    """Base class for all penpine errors."""


class ParseError(PenpineError):
    """Failure while parsing an HTTP message."""

    def __init__(self, message: str, *, offset: int | None = None, snippet: str | None = None):
        self.offset = offset
        self.snippet = snippet
        if offset is not None:
            message = f"{message} (offset={offset})"
        super().__init__(message)


class MalformedRequestError(ParseError):
    """Request violates HTTP/1.1 framing in strict mode."""


class BodyParseError(ParseError):
    """A typed body view could not be parsed."""


class LocatorError(PenpineError):
    """A locator expression is invalid or its target is absent."""


class BuildError(PenpineError):
    """Invalid RequestBuilder usage."""
