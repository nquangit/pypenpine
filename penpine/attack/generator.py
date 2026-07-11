"""PayloadGenerator contract: point-aware, yields TestCases."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from penpine.attack.models import InjectionPoint, TestCase


class PayloadGenerator(ABC):
    @abstractmethod
    def generate(self, point: InjectionPoint, request) -> Iterable[TestCase]:
        """Yield TestCases for this injection point on this base request."""
        raise NotImplementedError
