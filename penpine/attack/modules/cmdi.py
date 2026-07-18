"""Generic OS command injection (command-output reflection oracle)."""

from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import (
    GENERIC_ERROR_SIGNATURES,
    body_text,
    error_signature,
    marker,
)
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

# each template runs `echo <marker>`; the bare marker in the body means execution
CMDI_TEMPLATES = [
    ";echo {m}",
    "$(echo {m})",
    "`echo {m}`",
    "|echo {m}",
    "&&echo {m}",
    "\n echo {m}",
]


class CmdiGenerator(PayloadGenerator):
    def __init__(self, templates=None):
        self._templates = list(templates) if templates is not None else list(CMDI_TEMPLATES)

    def generate(self, point, request):
        for tmpl in self._templates:
            m = marker("cmdi")
            value = tmpl.format(m=m)
            yield TestCase(
                point=point,
                payload=Payload(value, technique="cmdi", meta={"marker": m}),
                attack_type=AttackType.CMDI,
            )


class CmdiValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = (
            list(signatures) if signatures is not None else list(GENERIC_ERROR_SIGNATURES)
        )

    def evaluate(self, test_case, response, baseline=None):
        m = test_case.payload.meta.get("marker")
        text = body_text(response)
        # execution: the marker appears but NOT as part of the echoed literal payload
        if m and m in text and test_case.payload.value not in text:
            return Finding(
                AttackType.CMDI,
                test_case.point,
                test_case.payload,
                Confidence.HIGH,
                f"command output reflected (marker {m})",
                request=test_case.request,
                response=response,
            )
        err = error_signature(response, baseline, self._signatures)
        if err is not None:
            return Finding(
                AttackType.CMDI,
                test_case.point,
                test_case.payload,
                Confidence.MEDIUM,
                f"error signature: {err.group(0)[:80]}",
                request=test_case.request,
                response=response,
            )
        return None


CMDI_MODULE = AttackModule(
    "cmdi",
    CmdiGenerator(),
    CmdiValidator(),
    attack_type=AttackType.CMDI,
    applies_to=("param", "form", "json", "multipart"),
    description="OS command injection (output-reflection oracle)",
)
