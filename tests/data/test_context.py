import threading

import pytest

from penpine.data.context import Context
from penpine.data.exceptions import DataError


def test_get_set_has_default():
    c = Context()
    assert c.get("x") is None
    assert c.get("x", "d") == "d"
    c.set("x", 1)
    assert c.get("x") == 1
    assert c.has("x") is True
    assert c.has("y") is False


def test_require_raises_when_missing():
    c = Context({"a": 1})
    assert c.require("a") == 1
    with pytest.raises(DataError):
        c.require("missing")


def test_update_keys_and_to_dict_snapshot():
    c = Context()
    c.update({"a": 1, "b": 2})
    assert set(c.keys()) == {"a", "b"}
    snap = c.to_dict()
    snap["a"] = 99
    assert c.get("a") == 1


def test_namespace_prefixes_keys():
    c = Context()
    view = c.namespace("userA")
    view.set("order_id", "123")
    assert c.get("userA.order_id") == "123"
    assert view.get("order_id") == "123"
    assert view.has("order_id") is True
    assert view.require("order_id") == "123"


def test_concurrent_writes_are_safe():
    c = Context()

    def writer(start):
        for i in range(start, start + 100):
            c.set(f"k{i}", i)

    threads = [threading.Thread(target=writer, args=(s,)) for s in (0, 100, 200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(c.keys()) == 300


def test_namespaced_require_missing_raises():
    c = Context()
    with pytest.raises(DataError):
        c.namespace("u").require("nope")
