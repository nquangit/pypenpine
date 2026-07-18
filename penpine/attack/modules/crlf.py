"""Generic CRLF / HTTP response header injection."""

from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import marker
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

INJECTED_HEADER = "X-Penpine-Inj"

# each template embeds a fresh marker; the response should carry it as a real header
CRLF_TEMPLATES = [
    "%0d%0a{h}: {m}",
    "\r\n{h}: {m}",
    "%E5%98%8A%E5%98%8D{h}: {m}",  # unicode CR/LF that some parsers normalize
    "%0d%0aSet-Cookie: {h}={m}",
]


class CrlfGenerator(PayloadGenerator):
    def __init__(self, templates=None, header=INJECTED_HEADER):
        self._templates = list(templates) if templates is not None else list(CRLF_TEMPLATES)
        self._header = header

    def generate(self, point, request):
        for tmpl in self._templates:
            m = marker("crlfpp")
            value = tmpl.format(h=self._header, m=m)
            yield TestCase(
                point=point,
                payload=Payload(value, technique="crlf", meta={"marker": m}),
                attack_type=AttackType.CRLF,
            )


class CrlfValidator(Validator):
    def evaluate(self, test_case, response, baseline=None):
        m = test_case.payload.meta.get("marker")
        if not m:
            return None
        for name, value in response.headers.items():
            if m in name or m in value:
                return Finding(
                    AttackType.CRLF,
                    test_case.point,
                    test_case.payload,
                    Confidence.HIGH,
                    f"CRLF-injected response header: {name}: {value}"[:120],
                    request=test_case.request,
                    response=response,
                )
        return None


CRLF_MODULE = AttackModule(
    "crlf",
    CrlfGenerator(),
    CrlfValidator(),
    attack_type=AttackType.CRLF,
    applies_to=("param", "form", "json", "header"),
    description="CRLF / HTTP response header injection",
)
