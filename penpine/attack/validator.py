"""Validator contract: judges an attack response against an optional baseline."""
from __future__ import annotations

from abc import ABC, abstractmethod

from penpine.attack.models import TestCase, Finding


class Validator(ABC):
    @abstractmethod
    def evaluate(self, test_case: TestCase, response, baseline) -> "Finding | None":
        """Return a Finding if the attack succeeded, else None.

        `baseline` is the unmodified request's response (may be None).
        """
        raise NotImplementedError
