import pytest

from penpine.data.exceptions import DataError
from penpine.data.profile import DataProfile


def test_get_with_default():
    p = DataProfile("admin", {"account_id": "A1"})
    assert p.name == "admin"
    assert p.get("account_id") == "A1"
    assert p.get("missing", "d") == "d"


def test_require_raises_when_missing():
    p = DataProfile("admin", {"account_id": "A1"})
    assert p.require("account_id") == "A1"
    with pytest.raises(DataError):
        p.require("missing")


def test_default_values_empty():
    assert DataProfile("guest").values == {}
