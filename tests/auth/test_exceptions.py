from penpine.exceptions import PenpineError
from penpine.auth.exceptions import AuthError, LoginError, RefreshError, AuthConfigError


def test_hierarchy():
    for cls in (LoginError, RefreshError, AuthConfigError):
        assert issubclass(cls, AuthError)
    assert issubclass(AuthError, PenpineError)
