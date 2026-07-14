"""Multi-request login via FlowLoginProvider (offline, no sockets).

The login is a Flow (fetch a CSRF token, then submit); FlowLoginProvider runs it
and maps captured context to a Session. Bundle it into an AuthProfile as usual.
    python -m samples.flow_login
"""
import asyncio

from penpine.auth import BearerAuth, FlowLoginProvider
from penpine.auth.profile import AuthProfile
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.extract import Extract
from penpine.flow import Flow, Step


class _FakeEngine:
    async def send(self, request):
        if "csrf=" in request.target:  # the submit step
            body = b'{"access_token": "tok-9"}'
        else:  # the initial page fetch
            body = b'{"csrf": "C1"}'
        return parse_response(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
            % (len(body), body)
        )


def demo():
    login = Flow(steps=[
        Step("page", request=Request.from_url("http://target.example/login"),
             capture=[Extract("csrf", json="$.csrf")]),
        Step("submit", request=Request.from_url("http://target.example/login?csrf={{csrf}}"),
             capture=[Extract("tok", json="$.access_token")]),
    ])
    provider = FlowLoginProvider(login, token_key="tok")
    profile = AuthProfile(name="demo", provider=provider, scheme=BearerAuth())
    session = asyncio.run(provider.login(_FakeEngine()))
    print("logged in via flow; token =", session.token, "| profile:", profile.name)
    return session


if __name__ == "__main__":
    demo()
