import logging

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.interceptor import RequestLogInterceptor


async def test_request_log_interceptor_logs_line_and_passes_through(caplog):
    ic = RequestLogInterceptor()
    req = Request.from_url("http://t/path?x=1")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        out = await ic.after_receive(req, resp)
    assert out is resp  # passthrough, unchanged
    msgs = [r.getMessage() for r in caplog.records]
    assert any("GET" in m and "-> 200" in m for m in msgs)


async def test_request_log_interceptor_reexported():
    from penpine.transport import RequestLogInterceptor as Exported

    assert Exported is RequestLogInterceptor
