from penpine.auth.exceptions import AuthConfigError, AuthError, LoginError, RefreshError
from penpine.exceptions import PenpineError


def test_hierarchy():
    for cls in (LoginError, RefreshError, AuthConfigError):
        assert issubclass(cls, AuthError)
    assert issubclass(AuthError, PenpineError)
