from penpine.core.message import Request
from penpine.data.identity import Identity
from penpine.data.context import Context
from penpine.data.extract import Extract
from tests.auth._fakes import FakeEngine


def create_order_resp(request):
    body = b'{"id":"ORD-123"}'
    return (b"HTTP/1.1 201 Created\r\nContent-Length: " + str(len(body)).encode()
            + b"\r\n\r\n" + body)


def use_order_resp(request):
    return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


async def test_user_a_creates_user_b_uses_via_shared_context():
    ctx = Context()
    alice = Identity("alice", manager=FakeEngine([create_order_resp]), context=ctx)
    bob = Identity("bob", manager=FakeEngine([use_order_resp]), context=ctx)

    resp = await alice.send(Request.from_url("http://h/orders"))
    alice.capture(resp, [Extract("order_id", json="$.id")])
    assert ctx.get("order_id") == "ORD-123"

    raw = (b"POST /use HTTP/1.1\r\nHost: h\r\nContent-Length: 15\r\n\r\n"
           b"id={{order_id}}")
    rendered = bob.render(Request.from_raw(raw))
    assert rendered.body.raw == b"id=ORD-123"
    assert rendered.headers["Content-Length"] == "10"

    bob_resp = await bob.send(rendered)
    assert bob_resp.status_code == 200
    assert bob.manager.sent[0].body.raw == b"id=ORD-123"
