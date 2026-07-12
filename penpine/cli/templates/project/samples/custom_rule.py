"""Custom analyzer ClassificationRule: tag injection points with attack types.

Pass your rule list to analyze(request, rules=[...]) to influence selection.
    python -m samples.custom_rule
"""
from penpine.attack.analyze import DEFAULT_RULES, analyze
from penpine.attack.analyze.rules import ClassificationRule
from penpine.attack.types import AttackType
from penpine.core.message import Request


class GraphQLRule(ClassificationRule):
    name = "graphql"

    def match(self, point):
        if point.name.lower() in {"query", "operationname", "variables"}:
            return {AttackType.SQLI}
        return set()


def demo():
    rules = list(DEFAULT_RULES) + [GraphQLRule()]
    req = Request.from_url("http://target.example/graphql?query=abc&id=1")
    analysis = analyze(req, rules=rules)
    print("tags:", {p.expr: p.attack_types for p in analysis})
    matched = analysis.for_attack(AttackType.SQLI)
    print("graphql points:", [p.expr for p in matched])
    return matched


if __name__ == "__main__":
    demo()
