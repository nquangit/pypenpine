"""Fake sender for runner tests (no sockets)."""
import re

from penpine.core.parse.http_parser import parse_response

_MARKER_RE = re.compile(rb"PENPINE_ECHO_[0-9a-fA-F]+")


class FakeSender:
    """async send(request). `script` is a list of raw bytes or callables(request)->bytes;
    the last entry repeats. Records sent requests on `.sent`."""

    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        raw = item(request) if callable(item) else item
        return parse_response(raw)


def reflect(request):
    """Echo any PENPINE_ECHO_* marker found in the request back in the response body."""
    raw = request.serialize()
    match = _MARKER_RE.search(raw)
    body = match.group(0) if match else b"baseline"
    return b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
