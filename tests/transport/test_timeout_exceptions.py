def test_timeout_hierarchy():
    from penpine.transport.exceptions import (
        ReadTimeout,
        TotalTimeout,
        TransportError,
        TransportTimeout,
    )

    assert issubclass(TransportTimeout, TransportError)
    assert issubclass(ReadTimeout, TransportTimeout)
    assert issubclass(TotalTimeout, TransportTimeout)
    assert issubclass(ReadTimeout, TransportError)


def test_reexported_from_transport_package():
    from penpine.transport import TotalTimeout, TransportTimeout
    from penpine.transport.exceptions import TotalTimeout as E_TotalTimeout

    assert TotalTimeout is E_TotalTimeout
    assert TransportTimeout is not None
