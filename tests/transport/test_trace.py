from penpine.transport.trace import InjectionInfo, current_injection


def test_defaults_to_none():
    assert current_injection.get() is None


def test_set_and_reset_round_trips():
    assert current_injection.get() is None
    token = current_injection.set(InjectionInfo(locator="json:$.user", value="' OR 1=1"))
    got = current_injection.get()
    assert got.locator == "json:$.user" and got.value == "' OR 1=1"
    current_injection.reset(token)
    assert current_injection.get() is None


def test_reexported_from_transport():
    from penpine.transport import InjectionInfo as A
    from penpine.transport import current_injection as B

    assert A is InjectionInfo and B is current_injection
