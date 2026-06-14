"""Analysis: the tagged-injection-point result of analyze()."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Analysis:
    request: object
    points: tuple

    def for_attack(self, attack_type: str) -> list:
        return [p for p in self.points if attack_type in p.attack_types]

    def by_kind(self) -> dict:
        grouped: dict = {}
        for point in self.points:
            grouped.setdefault(point.kind, []).append(point)
        return grouped

    def attack_types(self) -> set:
        return {tag for point in self.points for tag in point.attack_types}

    def all(self) -> list:
        return list(self.points)

    def __iter__(self):
        return iter(self.points)

    def __len__(self) -> int:
        return len(self.points)
