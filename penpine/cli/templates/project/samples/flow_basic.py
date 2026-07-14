"""A multi-step Flow with capture + templating (offline, no sockets).

login -> capture token -> next step uses {{token}}.
    python -m samples.flow_basic
"""
from penpine import Flow, Step
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.extract import Extract


class _FakeActor:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        if request.target.endswith("/login"):
            body = b'{"token": "abc123"}'
            return parse_response(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                % (len(body), body)
            )
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")


def demo():
    flow = Flow(
        actor=_FakeActor(),
        steps=[
            Step("login", request=Request.from_url("http://target.example/login"),
                 capture=[Extract("token", json="$.token")]),
            Step("act", request=Request.from_url("http://target.example/do?tok={{token}}")),
        ],
    )
    result = flow.run_sync()
    print("flow:", result.summary(), "token=", result.context.get("token"))
    return result


if __name__ == "__main__":
    demo()
