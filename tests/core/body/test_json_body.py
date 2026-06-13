import pytest
from penpine.core.body.json_body import JsonBody
from penpine.exceptions import BodyParseError


def test_parse_and_get():
    jb = JsonBody.from_bytes(b'{"user": {"id": 5, "name": "ann"}}')
    assert jb.get("$.user.id") == 5
    assert jb.get("$.user.name") == "ann"


def test_set_returns_new_and_reserializes():
    jb = JsonBody.from_bytes(b'{"a": 1}')
    jb2 = jb.set("$.a", 2)
    assert jb.get("$.a") == 1
    assert jb2.get("$.a") == 2
    assert b'"a": 2' in jb2.to_bytes() or b'"a":2' in jb2.to_bytes()


def test_invalid_json_raises():
    with pytest.raises(BodyParseError):
        JsonBody.from_bytes(b"{not json")
