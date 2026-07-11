import asyncio

import pytest

from penpine.attack import registry
from penpine.attack.analyze.analyzer import analyze
from penpine.attack.example import EchoGenerator, EchoValidator
from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import InjectionPoint, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.runner import Runner
from penpine.attack.validator import Validator
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from tests.attack._fakes import FakeSender, reflect


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def _ok(_request):
    return b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"


def _xss_module():
    return AttackModule("xss", EchoGenerator(), EchoValidator(), applies_to=("param",))


async def test_max_concurrency_bounds_fanout():
    state = {"live": 0, "peak": 0}

    class SlowSender:
        async def send(self, request):
            state["live"] += 1
            state["peak"] = max(state["peak"], state["live"])
            await asyncio.sleep(0.01)
            state["live"] -= 1
            return parse_response(_ok(request))

    req = Request.from_url("http://h/?a=1&b=2&c=3&d=4&e=5&f=6")
    runner = Runner(sender=SlowSender(), max_concurrency=2, capture_baseline=False)
    report = await runner.run(req, module=_xss_module(), points=analyze(req).all())
    assert report.summary()["sent"] >= 6
    assert state["peak"] <= 2


async def test_per_call_sender_override():
    registry.register(_xss_module())
    default = FakeSender([reflect])
    override = FakeSender([reflect])
    runner = Runner(sender=default)
    await runner.run(Request.from_url("http://h/?q=hi"), attack="xss", sender=override)
    assert override.sent  # override received the requests
    assert not default.sent  # instance default untouched


async def test_generator_provided_request_sent_verbatim():
    custom = Request.from_url("http://h/CUSTOM")

    class G(PayloadGenerator):
        def generate(self, point, request):
            yield TestCase(point=point, payload=Payload("X"), attack_type="t", request=custom)

    req = Request.from_url("http://h/?a=1")
    module = AttackModule("t", G(), EchoValidator(), applies_to=("param",))
    sender = FakeSender([reflect])
    await Runner(sender=sender).run(req, module=module, points=analyze(req).all())
    assert any(s.target == "/CUSTOM" for s in sender.sent)  # generator request honored


async def test_validator_error_keeps_response():
    class G(PayloadGenerator):
        def generate(self, point, request):
            yield TestCase(point=point, payload=Payload("X"), attack_type="t")

    class BadValidator(Validator):
        def evaluate(self, test_case, response, baseline):
            raise RuntimeError("oracle bug")

    req = Request.from_url("http://h/?a=1")
    module = AttackModule("t", G(), BadValidator(), applies_to=("param",))
    point = InjectionPoint.from_locator(req.locate("param:a"))
    report = await Runner(sender=FakeSender([reflect])).run(req, module=module, points=[point])
    assert len(report) == 1
    attempt = report.attempts[0]
    assert attempt.error is not None
    assert attempt.response is not None  # response preserved despite validator error
    assert attempt.finding is None


async def test_capture_baseline_false_skips_baseline():
    registry.register(_xss_module())
    sender = FakeSender([reflect])
    report = await Runner(sender=sender, capture_baseline=False).run(
        Request.from_url("http://h/?q=hi"), attack="xss"
    )
    assert report.baseline is None
    assert len(sender.sent) == len(report.attempts)  # no extra baseline send
