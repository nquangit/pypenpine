from penpine.attack.models import Confidence, InjectionPoint
from penpine.attack.modules.differential import TIME_SQLI_MODULE, TimeSqliModule
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


def _ok():
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class _TimingSender:
    """Advances a shared clock: a sleep payload asking for N=3 delays ~delay; the
    N=0 control and un-injected baseline are instant.

    `replace_at` URL-encodes the query value, so `SLEEP(3)` becomes `SLEEP%283%29`
    and `WAITFOR DELAY '0:0:3'` becomes `...0%3A0%3A3...`; we key on the delay
    VALUE (3) in both encoded and raw forms so the N=0 control never matches.
    """

    def __init__(self, clock, *, injectable, delay=3.0):
        self.clock = clock
        self.injectable = injectable
        self.delay = delay

    async def send(self, request):
        raw = request.serialize()
        delays = self.injectable and (
            b"%283%29" in raw or b"(3)" in raw or b"0%3A0%3A3" in raw or b"0:0:3" in raw
        )
        self.clock.advance((self.delay + 0.05) if delays else 0.001)
        return _ok()


async def test_time_module_flags_confirmed_delay():
    clock = _Clock()
    module = TimeSqliModule(delay=3, clock=clock)
    sender = _TimingSender(clock, injectable=True)
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="1")
    finding = await module.probe(point, Request.from_url("http://h/s?q=1"), sender)
    assert finding is not None
    assert finding.attack_type == AttackType.SQLI
    assert finding.confidence == Confidence.HIGH


async def test_time_module_no_finding_when_not_injectable():
    clock = _Clock()
    module = TimeSqliModule(delay=3, clock=clock)
    sender = _TimingSender(clock, injectable=False)  # nothing ever delays
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="1")
    finding = await module.probe(point, Request.from_url("http://h/s?q=1"), sender)
    assert finding is None


class _UniformlySlowSender:
    """Everything is slow — including the zero-delay control — so it is NOT injectable."""

    def __init__(self, clock, delay=3.0):
        self.clock = clock
        self.delay = delay

    async def send(self, request):
        self.clock.advance(self.delay + 0.05)
        return _ok()


async def test_time_module_no_finding_when_uniformly_slow():
    clock = _Clock()
    module = TimeSqliModule(delay=3, clock=clock)
    finding = await module.probe(
        InjectionPoint(expr="param:q", kind="param", name="q", value="1"),
        Request.from_url("http://h/s?q=1"),
        _UniformlySlowSender(clock),
    )
    assert finding is None


def test_time_module_metadata():
    assert TIME_SQLI_MODULE.name == "sqli-time"
    assert TIME_SQLI_MODULE.attack_type == AttackType.SQLI
    assert TIME_SQLI_MODULE.applies("param") is True
