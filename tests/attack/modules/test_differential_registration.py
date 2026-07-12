from penpine.attack import registry
from penpine.attack.modules import BUILTIN_MODULES, DIFFERENTIAL_MODULES, register_builtins
from penpine.attack.runner import Runner
from penpine.attack.types import AttackType
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


def test_register_builtins_registers_differential_by_name():
    register_builtins()
    assert registry.get("sqli-boolean").name == "sqli-boolean"
    assert registry.get("sqli-time").name == "sqli-time"


def test_differential_excluded_from_builtin_modules():
    names = {m.name for m in BUILTIN_MODULES}
    assert "sqli-boolean" not in names
    assert "sqli-time" not in names
    assert {m.name for m in DIFFERENTIAL_MODULES} == {"sqli-boolean", "sqli-time"}


def _resp(status, body):
    return parse_response(
        b"HTTP/1.1 %d X\r\nContent-Length: %d\r\n\r\n%s" % (status, len(body), body)
    )


class _BoolSender:
    def __init__(self):
        self.base = _resp(200, b"A" * 500)

    async def send(self, request):
        raw = request.serialize()
        if b"1%3D2" in raw or b"1=2" in raw or b"'1'%3D'2" in raw:
            return _resp(200, b"B" * 50)
        return self.base


async def test_end_to_end_boolean_via_runner():
    register_builtins()
    req = Request.from_url("http://h/s?q=hi")
    # differential (probe) modules are opt-in via module=; attack= only selects
    # signature modules of a category.
    report = await Runner(sender=_BoolSender(), capture_baseline=False).run(
        req, module=registry.get("sqli-boolean")
    )
    assert any(f.attack_type is AttackType.SQLI for f in report.findings)
    assert any(a.test_case.point.expr == "param:q" for a in report.attempts)
