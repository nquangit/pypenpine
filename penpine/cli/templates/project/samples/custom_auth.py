"""Custom AuthScheme + AuthProfile.

A scheme decides how auth material rides on each request. Bundle a provider +
scheme into an AuthProfile; profile.manager() gives a SessionManager that logs
in, attaches auth, and re-logs in on 401.
    python -m samples.custom_auth
"""
from penpine.auth import AuthProfile, JsonLoginProvider
from penpine.auth.scheme import AuthScheme
from penpine.auth.session import Session
from penpine.core.message import Request


class ApiKeyHeaderScheme(AuthScheme):
    """Attach the session token as a custom X-API-Key header."""

    def __init__(self, header="X-API-Key"):
        self.header = header

    def apply(self, request, session):
        return request.set_header(self.header, session.token or "")


def build_profile():
    provider = JsonLoginProvider(url="http://target.example/login",
                                 payload={"user": "demo", "pw": "demo"},
                                 token_path="$.access_token")
    return AuthProfile(name="demo", provider=provider, scheme=ApiKeyHeaderScheme())


def demo():
    profile = build_profile()
    # Offline: show the scheme applying a token (no network/login round-trip).
    applied = profile.scheme.apply(Request.from_url("http://target.example/api/me"),
                                   Session(token="secret-123"))
    present = b"X-API-Key: secret-123" in applied.serialize()
    print("auth header applied:", present)
    return applied


if __name__ == "__main__":
    demo()
