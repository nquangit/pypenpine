import penpine
from penpine.transport import (
    Engine, Connection, TLSConfig, ProxyConfig, Timeouts, Interceptor, RetrySignal,
)


def test_transport_exports_exist():
    assert all([Engine, Connection, TLSConfig, ProxyConfig, Timeouts,
                Interceptor, RetrySignal])


def test_top_level_reexports_engine():
    assert hasattr(penpine, "Engine")
    assert penpine.Engine is Engine
