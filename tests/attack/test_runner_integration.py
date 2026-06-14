import pytest

import penpine
from penpine.core.message import Request
from penpine.attack import Runner, Report, Attempt, registry, ECHO_MODULE
from tests.attack._fakes import FakeSender, reflect


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def test_runner_exposed_at_top_level():
    assert penpine.Runner is Runner


async def test_end_to_end_echo_module_via_registry():
    from penpine.attack.analyze import analyze
    registry.register(ECHO_MODULE)
    req = Request.from_url("http://h/?token=abc")
    report = await Runner(sender=FakeSender([reflect])).run(
        req, module=registry.get("echo"), points=analyze(req).all())
    assert isinstance(report, Report)
    assert report.findings
    assert all(isinstance(a, Attempt) for a in report)
    hit = report.findings[0]
    assert hit.attack_type == "echo"
    assert hit.request is not None
