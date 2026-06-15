"""Open-redirect module."""
from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.validator import Validator

CANARY_HOST = "penpine-canary.example"
REDIRECT_PAYLOADS = [f"https://{CANARY_HOST}/", f"//{CANARY_HOST}/", f"https:{CANARY_HOST}"]
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class RedirectGenerator(PayloadGenerator):
    def __init__(self, payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(REDIRECT_PAYLOADS)

    def generate(self, point, request):
        for value in self._payloads:
            yield TestCase(point=point, payload=Payload(value, technique="redirect"),
                           attack_type="open-redirect")


class RedirectValidator(Validator):
    def __init__(self, host=CANARY_HOST):
        self._host = host

    def evaluate(self, test_case, response, baseline=None):
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("Location", "")
            if self._host in location:
                return Finding("open-redirect", test_case.point, test_case.payload,
                               Confidence.HIGH, f"redirect Location to canary: {location}",
                               request=test_case.request, response=response)
        return None


REDIRECT_MODULE = AttackModule("open-redirect", RedirectGenerator(), RedirectValidator(),
                               applies_to=("param", "form", "json"),
                               description="open redirect")
