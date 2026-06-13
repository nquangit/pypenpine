import pytest

from penpine.auth.provider import AuthProvider, JsonLoginProvider, FormLoginProvider
from penpine.auth.exceptions import LoginError
from tests.auth._fakes import FakeEngine


async def test_json_provider_extracts_token():
    engine = FakeEngine([b'HTTP/1.1 200 OK\r\nContent-Length: 21\r\n\r\n{"access_token":"T1"}'])
    p = JsonLoginProvider("http://h/login", {"u": "a", "p": "b"})
    session = await p.login(engine)
    assert session.token == "T1"
    assert engine.sent[0].method == "POST"
    assert b'"u": "a"' in engine.sent[0].body.raw


async def test_json_provider_reads_expiry_ttl():
    import time
    raw = b'HTTP/1.1 200 OK\r\nContent-Length: 36\r\n\r\n{"access_token":"T","expires_in":60}'
    engine = FakeEngine([raw])
    p = JsonLoginProvider("http://h/login", {}, expires_path="$.expires_in")
    session = await p.login(engine)
    assert session.expires_at is not None
    assert abs(session.expires_at - (time.time() + 60)) < 5


async def test_json_provider_non_2xx_raises():
    engine = FakeEngine([b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"])
    p = JsonLoginProvider("http://h/login", {})
    with pytest.raises(LoginError):
        await p.login(engine)


async def test_json_provider_missing_token_raises():
    engine = FakeEngine([b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n{"nope":1}\n'])
    p = JsonLoginProvider("http://h/login", {})
    with pytest.raises(LoginError):
        await p.login(engine)


async def test_form_provider_captures_cookies():
    raw = (b"HTTP/1.1 200 OK\r\nSet-Cookie: sid=abc; Path=/\r\n"
           b"Set-Cookie: csrf=xyz\r\nContent-Length: 0\r\n\r\n")
    engine = FakeEngine([raw])
    p = FormLoginProvider("http://h/login", {"user": "a", "pass": "b"})
    session = await p.login(engine)
    assert ("sid", "abc") in session.cookies
    assert ("csrf", "xyz") in session.cookies


async def test_default_refresh_calls_login():
    engine = FakeEngine([b'HTTP/1.1 200 OK\r\nContent-Length: 21\r\n\r\n{"access_token":"T2"}'])
    p = JsonLoginProvider("http://h/login", {})
    session = await p.refresh(engine, None)
    assert session.token == "T2"


async def test_base_login_not_implemented():
    with pytest.raises(NotImplementedError):
        await AuthProvider().login(FakeEngine([]))
