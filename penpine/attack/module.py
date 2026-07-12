"""AttackModule: bundles a generator + validator + metadata."""

from __future__ import annotations

from penpine.attack.generator import PayloadGenerator
from penpine.attack.validator import Validator


class AttackModule:
    def __init__(
        self,
        name: str,
        generator: PayloadGenerator,
        validator: Validator,
        *,
        attack_type=None,
        applies_to: tuple = (),
        description: str = "",
    ):
        self.name = name
        self.generator = generator
        self.validator = validator
        self.attack_type = attack_type
        self.applies_to = tuple(applies_to)
        self.description = description

    def generate(self, point, request):
        return self.generator.generate(point, request)

    def evaluate(self, test_case, response, baseline=None):
        return self.validator.evaluate(test_case, response, baseline)

    def applies(self, kind: str) -> bool:
        return not self.applies_to or kind in self.applies_to
