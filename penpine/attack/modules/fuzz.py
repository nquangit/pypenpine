"""Generic edge/type-value fuzzing with error/anomaly detection."""

from __future__ import annotations

import uuid as _uuid

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import GENERIC_ERROR_SIGNATURES, error_signature
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

FUZZ_PAYLOADS = [
    "null",
    "none",
    "",
    "0",
    "1",
    "-1",
    "true",
    "false",
    "NaN",
    "Infinity",
    str(_uuid.uuid4()),
    str(2**63),
    str(-(2**63)),
    str(2**63 - 1),
    "1e308",
    "-1e308",
    "1" * 33000,
    "%n%n%n",
    "{{7*7}}",
    "[]",
    "{}",
    "$(:)",
    "\r\n",
    "\x00",
    "../",
    "🌀",
    "' OR ''='",
    "<x>",
    "-0",
    "0x1f",
    "1;",
    "   ",
    "9" * 40,
    "%00",
    "￿",
]


def _status(obj) -> int:
    return getattr(obj, "status_code", 0) or 0


def _blen(obj) -> int:
    return len(getattr(obj, "body", b"") or b"")


class FuzzGenerator(PayloadGenerator):
    def __init__(self, payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(FUZZ_PAYLOADS)

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(
                point=point, payload=Payload(value, technique="fuzz"), attack_type=AttackType.FUZZ
            )


class FuzzValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = (
            list(signatures) if signatures is not None else list(GENERIC_ERROR_SIGNATURES)
        )

    def _finding(self, test_case, response, confidence, evidence):
        return Finding(
            AttackType.FUZZ,
            test_case.point,
            test_case.payload,
            confidence,
            evidence,
            request=test_case.request,
            response=response,
        )

    def evaluate(self, test_case, response, baseline=None):
        status = _status(response)
        if status >= 500 and _status(baseline) < 500:
            conf = Confidence.HIGH if baseline is not None else Confidence.MEDIUM
            return self._finding(test_case, response, conf, f"server error status {status}")
        match = error_signature(response, baseline, self._signatures)
        if match is not None:
            return self._finding(
                test_case, response, Confidence.HIGH, f"error signature: {match.group(0)[:80]}"
            )
        if baseline is not None:
            b_status = _status(baseline)
            if status >= 400 and status // 100 != b_status // 100:
                return self._finding(
                    test_case, response, Confidence.MEDIUM, f"status change {b_status} -> {status}"
                )
            bl, rl = _blen(baseline), _blen(response)
            if bl and (rl >= 3 * bl or rl * 3 <= bl):
                return self._finding(
                    test_case, response, Confidence.MEDIUM, f"response size {bl} -> {rl} bytes"
                )
        return None


FUZZ_MODULE = AttackModule(
    "fuzz",
    FuzzGenerator(),
    FuzzValidator(),
    attack_type=AttackType.FUZZ,
    applies_to=(),  # all injectable kinds
    description="generic edge/type-value fuzzing (error & anomaly detection)",
)
