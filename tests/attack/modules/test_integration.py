import pytest

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.attack import registry
from penpine.attack.modules import register_builtins
from penpine.attack.runner import Runner


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


class SqlErrorSender:
    async def send(self, request):
        raw = request.serialize()
        if b"%27" in raw or b"%22" in raw or b"OR" in raw:
            body = b"You have an error in your SQL syntax near '%' at line 1"
        else:
            body = b"home page"
        return parse_response(
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


async def test_end_to_end_sqli_finding_via_runner():
    register_builtins()
    report = await Runner(sender=SqlErrorSender()).run(
        Request.from_url("http://h/?q=hi"), attack="sqli")
    assert report.attack_type == "sqli"
    assert report.findings, "expected at least one SQLi finding"
    finding = report.findings[0]
    assert finding.attack_type == "sqli"
    assert finding.confidence.name == "HIGH"
    assert finding.request is not None
    assert finding.point.expr == "param:q"
