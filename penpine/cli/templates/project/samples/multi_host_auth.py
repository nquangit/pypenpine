"""Two-host session: a cookie for the web host + a refresh-token-derived JWT for
the API host (offline, no sockets).

Real targets often split auth across hosts: a cookie (JSESSIONID) keeps the main
web session, while important actions on an API host need a short-lived JWT that
you obtain by exchanging a long-lived refresh token. This sample wires that up:

* FlowAuthProvider(login_flow, refresh_flow): login establishes the cookie +
  refresh token; refresh exchanges the refresh token for a fresh access token,
  carrying the cookie forward. When login has no access token yet, the session
  is born already-expired so the first send triggers the exchange.
* MultiScheme([HostScoped(CookieAuth(), web), HostScoped(BearerAuth(), api)]):
  the cookie only rides requests to the web host, the bearer only to the API
  host -- no cross-leak.

    python -m samples.multi_host_auth
"""
import asyncio
import base64
import json
import time

from penpine.auth import BearerAuth, CookieAuth, FlowAuthProvider, HostScoped, MultiScheme
from penpine.auth.profile import AuthProfile
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.extract import Extract
from penpine.flow import Flow, Step

WEB_HOST = "web.example"
API_HOST = "api.example"


def _make_jwt(payload: dict) -> str:
    def seg(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{seg({'alg': 'none'})}.{seg(payload)}.sig"


class _FakeEngine:
    """Serves the login (cookie + refresh token) and the token exchange (JWT)."""

    async def send(self, request):
        if "/token" in request.target:  # refresh exchange
            jwt = _make_jwt({"exp": int(time.time()) + 3600})
            body = b'{"access_token": "%s"}' % jwt.encode()
            head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
            return parse_response(head % (len(body), body))
        # login: hand out the web cookie + a refresh token, but no access token yet
        body = b'{"refresh_token": "R1"}'
        head = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Set-Cookie: JSESSIONID=SID-abc; Path=/\r\nContent-Length: %d\r\n\r\n%s"
        )
        return parse_response(head % (len(body), body))


def build_profile() -> AuthProfile:
    login_flow = Flow(steps=[
        Step("login", request=Request.from_url(f"https://{WEB_HOST}/login"),
             capture=[Extract("JSESSIONID", cookie="JSESSIONID"),
                      Extract("refresh_token", json="$.refresh_token")]),
    ])
    refresh_flow = Flow(steps=[
        Step("exchange", request=Request.from_url(f"https://{API_HOST}/token?rt={{{{refresh_token}}}}"),
             capture=[Extract("access_token", json="$.access_token")]),
    ])
    provider = FlowAuthProvider(
        login_flow, refresh_flow,
        token_key="access_token",
        cookie_keys=["JSESSIONID"],
        data_keys=["refresh_token"],
    )
    scheme = MultiScheme([
        HostScoped(CookieAuth(), WEB_HOST),   # cookie only to the web host
        HostScoped(BearerAuth(), API_HOST),   # bearer only to the API host
    ])
    return AuthProfile(name="demo", provider=provider, scheme=scheme)


def demo():
    profile = build_profile()
    engine = _FakeEngine()

    # 1) login: cookie + refresh token, no access token -> already expired.
    session = asyncio.run(profile.provider.login(engine))
    print("after login   : cookie =", session.cookies,
          "| token =", session.token, "| expired =", session.is_expired())

    # 2) refresh: exchange the refresh token for a JWT, cookie carried over.
    session = asyncio.run(profile.provider.refresh(engine, session))
    print("after refresh : cookie =", session.cookies,
          "| token =", session.token[:24] + "...")

    # 3) host scoping: each request gets only its own material.
    web = profile.scheme.apply(Request.from_url(f"https://{WEB_HOST}/home"), session)
    api = profile.scheme.apply(Request.from_url(f"https://{API_HOST}/transfer"), session)
    print("web request   : Cookie =", web.headers.get("Cookie"),
          "| Authorization =", web.headers.get("Authorization"))
    print("api request   : Cookie =", api.headers.get("Cookie"),
          "| Authorization =", (api.headers.get("Authorization") or "")[:24] + "...")
    return session


if __name__ == "__main__":
    demo()
