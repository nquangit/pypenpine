"""analyze(): classify a request's injection candidates into tagged points."""
from __future__ import annotations

import dataclasses

from penpine.attack.models import InjectionPoint
from penpine.attack.analyze.analysis import Analysis
from penpine.attack.analyze.rules import DEFAULT_RULES


def analyze(request, *, rules=None, kinds=None) -> Analysis:
    active = DEFAULT_RULES if rules is None else list(rules)
    points = []
    for loc in request.injection_candidates(kinds=kinds):
        base = InjectionPoint.from_locator(loc)
        tags: set = set()
        for rule in active:
            tags |= rule.match(base)
        points.append(dataclasses.replace(base, attack_types=tuple(sorted(tags))))
    return Analysis(request=request, points=tuple(points))
