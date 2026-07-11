from penpine.attack.models import Confidence, Finding, Payload
from penpine.attack.runner import Runner
from penpine.core.message import Request


class _FakeDiff:
    name = "sqli-boolean"
    applies_to = ("param",)
    select_attack_type = "sqli"

    def __init__(self, behavior):
        self._behavior = behavior  # callable(point) -> Finding | None | raises

    def applies(self, kind):
        return not self.applies_to or kind in self.applies_to

    async def probe(self, point, request, sender, *, baseline=None):
        return self._behavior(point)


def _finding(point):
    return Finding(
        attack_type="sqli-boolean",
        point=point,
        payload=Payload("' AND 1=1-- -"),
        confidence=Confidence.HIGH,
        evidence="boolean-based blind SQLi",
    )


async def test_runner_probes_each_point_and_collects_findings():
    module = _FakeDiff(_finding)
    req = Request.from_url("http://h/s?q=hi")
    report = await Runner(capture_baseline=False).run(req, module=module, sender=_NullSender())
    assert len(report.findings) >= 1
    assert report.attack_type == "sqli-boolean"
    assert all(a.test_case.point.kind == "param" for a in report.attempts)


async def test_runner_probe_none_yields_no_findings():
    report = await Runner(capture_baseline=False).run(
        Request.from_url("http://h/s?q=hi"), module=_FakeDiff(lambda p: None), sender=_NullSender()
    )
    assert report.findings == []
    assert len(report.attempts) >= 1


async def test_runner_probe_error_isolated():
    def boom(point):
        raise RuntimeError("probe failed")

    report = await Runner(capture_baseline=False).run(
        Request.from_url("http://h/s?q=hi&x=1"), module=_FakeDiff(boom), sender=_NullSender()
    )
    assert report.summary()["failed"] == len(report.attempts)
    assert report.findings == []


class _NullSender:
    async def send(self, request):
        from penpine.core.parse.http_parser import parse_response

        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
