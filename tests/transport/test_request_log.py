import logging

import pytest
from rich.console import Console

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.interceptor import RequestLogInterceptor


@pytest.fixture(autouse=True)
def _capturable_penpine_logger():
    log = logging.getLogger("penpine")
    saved_propagate = log.propagate
    saved_handlers = log.handlers[:]
    log.propagate = True
    log.handlers.clear()
    log.setLevel(logging.INFO)
    yield
    log.propagate = saved_propagate
    log.handlers[:] = saved_handlers


def _recording(ic):
    """Point the interceptor's renderer at a recording console."""
    ic._table._console = Console(record=True, width=80)
    return ic._table._console


async def test_before_send_produces_no_output(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    req = Request.from_url("http://t/path?x=1")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
    assert caplog.records == []  # no log record on send
    assert rec.export_text().strip() == ""  # nothing rendered on send


async def test_after_receive_renders_one_row_and_audits(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    req = Request.from_url("http://t/path?x=1")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        out = await ic.after_receive(req, resp)
    assert out is resp
    text = rec.export_text()
    assert "200" in text and "GET" in text and "/path?x=1" in text  # rendered row
    # exactly one audit record, tagged for file-only routing
    reqrecs = [r for r in caplog.records if getattr(r, "_penpine_request", False)]
    assert len(reqrecs) == 1
    assert "200" in reqrecs[0].getMessage() and "/path?x=1" in reqrecs[0].getMessage()


async def test_on_error_renders_failure_row_and_audits(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    req = Request.from_url("http://t/down")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        await ic.on_error(req, ConnectionRefusedError("refused"))
    text = rec.export_text()
    assert "ERR" in text and "/down" in text and "ConnectionRefusedError" in text
    reqrecs = [r for r in caplog.records if getattr(r, "_penpine_request", False)]
    assert len(reqrecs) == 1
    assert "ERR" in reqrecs[0].getMessage()


async def test_failure_is_visible_without_a_response(caplog):
    # Regression (rephrased): a send that fails never reaches after_receive, so
    # the failure must be recorded via on_error — failed requests stay visible.
    ic = RequestLogInterceptor()
    _recording(ic)
    req = Request.from_url("http://t/path")
    with caplog.at_level(logging.INFO, logger="penpine.transport"):
        await ic.before_send(req)
        await ic.on_error(req, TimeoutError("boom"))
    assert any(getattr(r, "_penpine_request", False) for r in caplog.records)


async def test_level_gating_suppresses_output(caplog):
    ic = RequestLogInterceptor()
    rec = _recording(ic)
    logging.getLogger("penpine").setLevel(logging.WARNING)  # above INFO
    req = Request.from_url("http://t/path")
    resp = parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    await ic.before_send(req)
    await ic.after_receive(req, resp)
    assert rec.export_text().strip() == ""  # nothing rendered
    assert caplog.records == []  # nothing logged


async def test_request_log_interceptor_reexported():
    from penpine.transport import RequestLogInterceptor as Exported

    assert Exported is RequestLogInterceptor
