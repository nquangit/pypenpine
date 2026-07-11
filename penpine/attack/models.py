"""Attack-framework data model. Pure data, no network."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

_REQUEST_LINE_KINDS = {"method", "target", "version"}


@dataclass(frozen=True)
class InjectionPoint:
    expr: str
    kind: str
    name: str = ""
    value: object = None
    attack_types: tuple = ()

    @classmethod
    def from_locator(cls, loc) -> InjectionPoint:
        kind = loc.kind
        name = getattr(loc, "name", "") or ""
        expr = kind if kind in _REQUEST_LINE_KINDS else f"{kind}:{name}"
        return cls(expr=expr, kind=kind, name=name, value=getattr(loc, "value", None))


@dataclass(frozen=True)
class Payload:
    value: str
    technique: str = ""
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # not a pytest test class
    point: InjectionPoint
    payload: Payload
    attack_type: str
    request: object | None = None
    marker: str | None = None
    meta: dict = field(default_factory=dict)


class Confidence(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass
class Finding:
    attack_type: str
    point: InjectionPoint
    payload: Payload
    confidence: Confidence
    evidence: str
    request: object | None = None
    response: object | None = None
    meta: dict = field(default_factory=dict)
