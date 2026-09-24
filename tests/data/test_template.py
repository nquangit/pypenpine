import pytest

from penpine.core.headers import Headers
from penpine.core.message import Request
from penpine.data.context import Context
from penpine.data.exceptions import TemplateError
from penpine.data.profile import DataProfile
from penpine.data.template import build_mapping, render


def test_render_substitutes_target_header_body():
    req = Request(
        method="POST",
        target="/orders/{{order_id}}",
        headers=Headers([("Host", "h"), ("X-Trace", "{{trace}}")]),
        body=b"id={{order_id}}",
    )
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


def test_render_text_substitutes_and_strict():
    import pytest

    from penpine.data.exceptions import TemplateError
    from penpine.data.template import render_text

    assert render_text("hi {{name}} #{{id}}", {"name": "al", "id": 7}) == "hi al #7"
    assert render_text("keep {{missing}}", {}, strict=False) == "keep {{missing}}"
    with pytest.raises(TemplateError):
        render_text("{{missing}}", {}, strict=True)


def test_render_request_still_works_via_render_text():
    from penpine.core.message import Request
    from penpine.data.template import render

    req = Request.from_url("http://h/p?q={{v}}")
    out = render(req, {"v": "X"})
    assert "q=X" in out.target


def test_render_resolves_placeholder_set_via_form_field():
    # set_form_field percent-encodes the value, turning {{x}} into %7B%7Bx%7D%7D.
    # render must still resolve it (the reported bug) and re-encode the result.
    req = (
        Request(method="POST", target="/login", headers=Headers([("Host", "h")]))
        .set_header("Content-Type", "application/x-www-form-urlencoded")
        .set_form_field("UserName", "alice")
        .set_form_field("dse_sessionId", "{{dse_sessionId}}")
    )
    assert b"%7B%7B" in req.body.raw  # confirm it was encoded at set-time
    out = render(req, {"dse_sessionId": "SID-123"})
    assert out.body.form.get("dse_sessionId") == "SID-123"
    assert out.body.form.get("UserName") == "alice"
    assert b"%7B%7B" not in out.body.raw


def test_render_form_field_value_is_reencoded_on_the_wire():
    # A resolved value with reserved chars must be encoded, not injected raw.
    req = (
        Request(method="POST", target="/login", headers=Headers([("Host", "h")]))
        .set_header("Content-Type", "application/x-www-form-urlencoded")
        .set_form_field("token", "{{tok}}")
    )
    out = render(req, {"tok": "a b&c=d"})
    assert out.body.form.get("token") == "a b&c=d"  # round-trips through decode
    assert b"a b&c=d" not in out.body.raw  # ...because it was encoded on the wire


def test_render_resolves_placeholder_set_via_set_param():
    req = Request(method="GET", target="/s", headers=Headers([("Host", "h")])).set_param(
        "next", "{{dest}}"
    )
    assert "%7B%7B" in req.target
    out = render(req, {"dest": "/home"})
    assert out.locate("param:next").value == "/home"


def test_render_leaves_malformed_query_untouched_without_placeholders():
    req = Request(method="GET", target="/s?a=1&b=2 3", headers=Headers([("Host", "h")]))
    out = render(req, {})
    assert out.target == "/s?a=1&b=2 3"
