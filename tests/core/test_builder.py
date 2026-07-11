import json

import pytest

from penpine.core.builder import RequestBuilder
from penpine.exceptions import BuildError


def test_build_json_request_sets_headers_and_length():
    r = RequestBuilder().method("POST").url("https://h/api").json({"a": 1}).build()
    assert r.method == "POST"
    assert r.headers["Content-Type"] == "application/json"
    assert r.headers["Content-Length"] == str(len(r.body.raw))
    assert json.loads(r.body.raw) == {"a": 1}
    assert r.meta.host == "h"


def test_build_requires_url():
    with pytest.raises(BuildError):
        RequestBuilder().method("GET").build()


def test_form_builder():
    r = RequestBuilder().method("POST").url("http://h/x").form({"a": "1"}).build()
    assert r.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert r.body.raw == b"a=1"
