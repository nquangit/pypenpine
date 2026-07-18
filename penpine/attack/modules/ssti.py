"""Generic server-side template injection (arithmetic-eval oracle)."""

from __future__ import annotations

import secrets

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

# each template takes two integers a, b; the response should contain a*b if evaluated
SSTI_TEMPLATES = ["{{%d*%d}}", "${%d*%d}", "#{%d*%d}", "<%%= %d*%d %%>", "${{%d*%d}}", "@(%d*%d)"]


class SstiGenerator(PayloadGenerator):
    def __init__(self, templates=None):
        self._templates = list(templates) if templates is not None else list(SSTI_TEMPLATES)

    def generate(self, point, request):
        for tmpl in self._templates:
            a = secrets.randbelow(9000) + 1000
            b = secrets.randbelow(9000) + 1000
            expr = tmpl % (a, b)
            yield TestCase(
                point=point,
                payload=Payload(expr, technique="ssti", meta={"product": a * b, "expr": expr}),
                attack_type=AttackType.SSTI,
            )


class SstiValidator(Validator):
    def evaluate(self, test_case, response, baseline=None):
        meta = test_case.payload.meta
        product, expr = meta.get("product"), meta.get("expr", test_case.payload.value)
        if product is None:
            return None
        text = body_text(response)
        if str(product) in text and expr not in text:
            return Finding(
                AttackType.SSTI,
                test_case.point,
                test_case.payload,
                Confidence.HIGH,
                f"template expression evaluated to {product}",
                request=test_case.request,
                response=response,
            )
        return None


SSTI_MODULE = AttackModule(
    "ssti",
    SstiGenerator(),
    SstiValidator(),
    attack_type=AttackType.SSTI,
    applies_to=("param", "form", "json", "multipart"),
    description="server-side template injection (eval oracle)",
)
