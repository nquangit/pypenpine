"""Fake sender for flow tests (no sockets)."""

from penpine.core.parse.http_parser import parse_response
from penpine.data.profile import DataProfile


def response(body=b"ok", status=b"200 OK", headers=b""):
    head = b"HTTP/1.1 %s\r\n%sContent-Length: %d\r\n\r\n%s" % (
        status,
        headers,
        len(body),
        body,
    )
    return parse_response(head)


class FakeActor:
    """async send(request). `script` is a list of Response objects or
    callables(request)->Response; the last entry repeats. Records sent
    requests on `.sent`. Optional `.data` (DataProfile) for template merge."""

    def __init__(self, name="actor", script=None, data=None):
        self.name = name
        self._script = list(script or [response()])
        self._i = 0
        self.sent = []
        self.data = DataProfile(name, dict(data or {}))

    async def send(self, request):
        self.sent.append(request)
        item = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        return item(request) if callable(item) else item
