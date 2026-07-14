import logging

import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.interceptor import RequestLogInterceptor


@pytest.fixture(autouse=True)
def _capturable_penpine_logger():
    log = logging.getLogger("penpine")
    saved_propagate = log.propagate
    saved_handlers = log.handlers[:]
    log.propagate = True  # let caplog capture via propagation to root
    log.handlers.clear()  # remove any console/file handler left by configure_logging
    yield
    log.propagate = saved_propagate
    log.handlers[:] = saved_handlers


async def test_request_logged_on_send_even_without_a_response(caplog):
    # A request that is sent but never gets a response (the real send raises after
    # before_send, so after_receive is never called) must STILL be logged.
    # Regression: the interceptor used to log only in after_receive, so failed /
    # unreachable requests were invisible (a down target logged nothing).
    ic = RequestLogInterceptor()
    req = Request.from_url("http://t/path?x=1")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)  # sent; the real send then raises -> no after_receive
    msgs = [r.getMessage() for r in caplog.records]
    assert any("GET" in m and "/path" in m for m in msgs), (
        "the request attempt must be logged on send, not only on response"
    )


async def test_request_and_response_logged_and_passthrough(caplog):
    ic = RequestLogInterceptor()
    req = Request.from_url("http://t/path?x=1")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        out = await ic.after_receive(req, resp)
    assert out is resp  # passthrough, unchanged
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "GET" in text and "/path?x=1" in text  # request line
    assert "200" in text  # response status
    assert "B" in text  # humanized size unit present
    assert len(caplog.records) == 2  # one on send, one on receive


async def test_target_with_brackets_is_escaped(caplog):
    ic = RequestLogInterceptor()
    req = Request.from_url("http://t/path?q=%5Bbold%5D")  # decodes to [bold]
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
    text = "\n".join(r.getMessage() for r in caplog.records)
    # escaped for rich markup: the raw message carries a backslash-escaped bracket
    assert "\\[" in text or "[bold]" not in text


async def test_request_log_interceptor_reexported():
    from penpine.transport import RequestLogInterceptor as Exported

    assert Exported is RequestLogInterceptor
