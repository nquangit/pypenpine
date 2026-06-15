"""Custom PayloadGenerator: yield TestCases (payload + metadata) for a point.

Plug it into an AttackModule (see custom_module.py) to use it in a run.
    python -m samples.custom_payload
"""
from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import InjectionPoint, Payload, TestCase


class HeaderSmugglingGenerator(PayloadGenerator):
    """Emit a few CRLF / header-smuggling probes for any injection point."""

    PAYLOADS = ["x\r\nX-Injected: 1", "x%0d%0aX-Injected:%201"]

    def __init__(self, payloads=None):
        self.payloads = list(payloads) if payloads is not None else list(self.PAYLOADS)

    def generate(self, point, request):
        for value in self.payloads:
            yield TestCase(point=point, payload=Payload(value, technique="crlf"),
                           attack_type="crlf")


def demo():
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="hi")
    cases = list(HeaderSmugglingGenerator().generate(point, None))
    print(f"generated {len(cases)} test cases:")
    for tc in cases:
        print("  ", tc.payload.technique, repr(tc.payload.value))
    return cases


if __name__ == "__main__":
    demo()
