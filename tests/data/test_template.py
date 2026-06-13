import pytest

from penpine.core.message import Request
from penpine.core.headers import Headers
from penpine.data.context import Context
from penpine.data.profile import DataProfile
from penpine.data.template import render, build_mapping
from penpine.data.exceptions import TemplateError


def test_render_substitutes_target_header_body():
    req = Request(method="POST", target="/orders/{{order_id}}",
                  headers=Headers([("Host", "h"), ("X-Trace", "{{trace}}")]),
                  body=b"id={{order_id}}")
    out = render(req, {"order_id": "123", "trace": "abc"})
    assert out.target == "/orders/123"
    assert out.headers["X-Trace"] == "abc"
    assert out.body.raw == b"id=123"
    assert out.headers["Content-Length"] == "6"


def test_render_strict_unknown_raises():
    req = Request(method="GET", target="/{{missing}}", headers=Headers([("Host", "h")]))
    with pytest.raises(TemplateError):
        render(req, {})


def test_render_non_strict_leaves_unknown():
    req = Request(method="GET", target="/{{missing}}", headers=Headers([("Host", "h")]))
    out = render(req, {}, strict=False)
    assert out.target == "/{{missing}}"


def test_render_dotted_key_is_literal():
    req = Request(method="GET", target="/{{userA.order_id}}", headers=Headers([("Host", "h")]))
    out = render(req, {"userA.order_id": "9"})
    assert out.target == "/9"


def test_build_mapping_precedence_data_lt_context_lt_extra():
    data = DataProfile("p", {"k": "data", "only_data": "d"})
    ctx = Context({"k": "ctx", "only_ctx": "c"})
    mapping = build_mapping(context=ctx, data=data, extra={"k": "extra"})
    assert mapping["k"] == "extra"
    assert mapping["only_data"] == "d"
    assert mapping["only_ctx"] == "c"


def test_build_mapping_accepts_plain_dicts():
    mapping = build_mapping(context={"a": 1}, data={"b": 2})
    assert mapping == {"a": 1, "b": 2}
