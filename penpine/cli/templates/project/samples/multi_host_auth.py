"""Two-host session, end to end: a cookie for the web host + a refresh-token-
derived JWT for the API host (offline, no sockets).

Real targets often split auth across hosts: a cookie (JSESSIONID) keeps the main
web session, while important actions on an API host need a short-lived JWT that
you obtain by exchanging a long-lived refresh token. This sample wires the whole
thing and then just calls `send` -- login, refresh, and attaching the right
credential to each host all happen automatically inside the SessionManager.

The pieces, and where each one goes:

    provider = FlowAuthProvider(login_flow, refresh_flow, ...)  # HOW to get creds
    scheme   = MultiScheme([HostScoped(CookieAuth(), web),      # WHERE creds ride
                            HostScoped(BearerAuth(), api)])
    profile  = AuthProfile(name, provider=provider, scheme=scheme)   # bundle
    mgr      = profile.manager(...)                                  # a SessionManager
    mgr.send_sync(request)   # logs in / refreshes as needed, applies the scheme

    python -m samples.multi_host_auth
"""
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


def _resp(body: bytes, extra_headers: bytes = b"") -> object:
    head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n%sContent-Length: %d\r\n\r\n%s"
    return parse_response(head % (extra_headers, len(body), body))


class _FakeEngine:
    """Routes by path: the login endpoint, the token-exchange endpoint, and the
    two real endpoints. Records every request it sees on `.sent`."""

    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        target = request.target
        if "/login" in target:  # establish the web cookie + a refresh token
            return _resp(b'{"refresh_token": "R1"}', b"Set-Cookie: JSESSIONID=SID-abc; Path=/\r\n")
        if "/token" in target:  # exchange the refresh token for a fresh JWT
            jwt = _make_jwt({"exp": int(time.time()) + 3600})
            return _resp(b'{"access_token": "%s"}' % jwt.encode())
        return _resp(b'{"ok": true}')  # the actual protected endpoints


def build_profile() -> AuthProfile:
    # HOW to get credentials: log in (cookie + refresh token), then exchange the
    # refresh token for an access token whenever it is needed.
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
        token_key="access_token",     # -> Session.token (its JWT `exp` sets expiry)
        cookie_keys=["JSESSIONID"],   # -> Session.cookies
        data_keys=["refresh_token"],  # -> Session.data, carried across each refresh
    )
    # WHERE credentials ride: cookie only to the web host, bearer only to the API host.
    scheme = MultiScheme([
        HostScoped(CookieAuth(), WEB_HOST),
        HostScoped(BearerAuth(), API_HOST),
    ])
    return AuthProfile(name="demo", provider=provider, scheme=scheme)


def demo():
    profile = build_profile()
    engine = _FakeEngine()

    # One SessionManager drives everything. Both the auth flows (login/refresh)
    # and the actual sends go through our fake engine here; in real use you'd
    # pass a real Engine (optionally one per identity, routed via a proxy).
    with profile.manager(auth_engine=engine, send_engine=engine) as mgr:
        # First call: no session yet -> auto-login. Login has no access token of
        # its own, so the provider immediately runs the refresh flow to fetch one
        # -- the session is fully ready before this request even goes out.
        mgr.send_sync(Request.from_url(f"https://{WEB_HOST}/home"))    # cookie attached
        mgr.send_sync(Request.from_url(f"https://{API_HOST}/transfer"))  # bearer attached, not None

    # What the engine actually saw, in order -- the full lifecycle:
    print("request lifecycle:")
    for r in engine.sent:
        host = r.meta.host or r.headers.get("Host", "?")
        print(f"  {r.method:4} {host}{r.target.split('?')[0]}")

    # Prove the scoping on the two protected requests: each host got only its own
    # credential (the login/token-exchange requests are the auth plumbing).
    home = next(r for r in engine.sent if r.target.startswith("/home"))
    transfer = next(r for r in engine.sent if r.target.startswith("/transfer"))
    print("\nscoping on the wire:")
    print("  web /home     -> Cookie:", home.headers.get("Cookie"),
          "| Authorization:", home.headers.get("Authorization"))
    print("  api /transfer -> Cookie:", transfer.headers.get("Cookie"),
          "| Authorization:", (transfer.headers.get("Authorization") or "")[:28] + "...")
    print("\nsession now holds token =", mgr.session.token is not None,
          "| cookies =", mgr.session.cookies)
    return mgr.session


if __name__ == "__main__":
    demo()
