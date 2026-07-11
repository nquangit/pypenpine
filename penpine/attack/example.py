"""EchoModule: a trivial reflection-detecting module proving the contracts."""

from __future__ import annotations

import secrets

from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.validator import Validator


class EchoGenerator(PayloadGenerator):
    def generate(self, point, request):
        marker = f"PENPINE_ECHO_{secrets.token_hex(4)}"
        yield TestCase(
            point=point,
            payload=Payload(marker, technique="echo"),
            attack_type="echo",
            marker=marker,
        )


class EchoValidator(Validator):
    def evaluate(self, test_case, response, baseline=None):
        if test_case.marker and test_case.marker.encode() in response.body.raw:
            return Finding(
                attack_type="echo",
                point=test_case.point,
                payload=test_case.payload,
                confidence=Confidence.HIGH,
                evidence="marker reflected in response body",
                request=test_case.request,
                response=response,
            )
        return None


ECHO_MODULE = AttackModule(
    "echo",
    EchoGenerator(),
    EchoValidator(),
    applies_to=("param", "json", "form", "header"),
    description="reflection echo probe",
)
