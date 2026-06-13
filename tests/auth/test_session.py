import time
from penpine.auth.session import Session


def test_defaults():
    s = Session()
    assert s.token is None
    assert s.cookies == []
    assert s.headers == []
    assert s.data == {}
    assert s.expires_at is None
    assert s.issued_at <= time.time()


def test_is_expired_without_expiry_is_false():
    assert Session().is_expired() is False


def test_is_expired_true_and_skew():
    past = Session(expires_at=time.time() - 1)
    assert past.is_expired() is True
    future = Session(expires_at=time.time() + 100)
    assert future.is_expired() is False
    assert future.is_expired(skew=200) is True
