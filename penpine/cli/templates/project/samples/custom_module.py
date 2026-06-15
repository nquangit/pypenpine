"""Wire a generator + validator into a registered AttackModule.

Once registered, `Runner.run(req, attack="crlf-leak")` (or module=MODULE) selects
points, generates payloads, sends, and validates end to end.
    python -m samples.custom_module
"""
from penpine.attack import Runner, registry
from penpine.attack.analyze import analyze
from penpine.attack.module import AttackModule
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response

from samples.custom_payload import HeaderSmugglingGenerator
from samples.custom_validator import StackTraceValidator

MODULE = AttackModule("crlf-leak", HeaderSmugglingGenerator(), StackTraceValidator(),
                      applies_to=("param", "header"),
                      description="sample CRLF probe + error-leak detector")


def register():
    registry.register(MODULE, replace=True)


class _Sender:
    """Offline fake: leaks a stack trace when a probe was injected."""

    async def send(self, request):
        leaked = b"X-Injected" in request.serialize()
        body = b"Traceback (most recent call last): boom" if leaked else b"ok"
        return parse_response(b"HTTP/1.1 200 X\r\nContent-Length: %d\r\n\r\n%s"
                              % (len(body), body))


def demo():
    register()
    req = Request.from_url("http://target.example/search?q=hi")
    report = Runner(sender=_Sender()).run_sync(req, module=MODULE, points=analyze(req).all())
    print("summary:", report.summary())
    return report


if __name__ == "__main__":
    demo()
