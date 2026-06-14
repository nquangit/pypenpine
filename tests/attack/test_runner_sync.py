import pytest

from penpine.core.message import Request
from penpine.attack import registry
from penpine.attack.module import AttackModule
from penpine.attack.example import EchoGenerator, EchoValidator
from penpine.attack.runner import Runner
from tests.attack._fakes import FakeSender, reflect


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def test_run_sync_returns_report_and_context_manager():
    registry.register(AttackModule("xss", EchoGenerator(), EchoValidator(),
                                   applies_to=("param",)))
    with Runner(sender=FakeSender([reflect])) as runner:
        report = runner.run_sync(Request.from_url("http://h/?q=hi"), attack="xss")
        assert report.findings
        assert report.summary()["sent"] >= 1
