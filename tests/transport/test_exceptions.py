from penpine.exceptions import PenpineError
from penpine.transport.exceptions import (
    TransportError, ConnectError, TLSError, ProxyError,
    ReadTimeout, IncompleteResponseError,
)
from penpine.transport.timeouts import Timeouts


def test_hierarchy():
    for cls in (ConnectError, TLSError, ProxyError, ReadTimeout, IncompleteResponseError):
        assert issubclass(cls, TransportError)
    assert issubclass(TransportError, PenpineError)


def test_timeouts_defaults():
    t = Timeouts()
    assert t.connect == 10.0
    assert t.read == 30.0
    assert t.total is None
    assert Timeouts(connect=1.0).connect == 1.0
