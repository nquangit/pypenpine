"""Error-based SQL injection module."""

from __future__ import annotations

import re

from penpine.attack.analyze.detectors import is_numeric
from penpine.attack.generator import PayloadGenerator
from penpine.attack.models import Confidence, Finding, Payload, TestCase
from penpine.attack.module import AttackModule
from penpine.attack.modules._common import body_text, search_signatures
from penpine.attack.types import AttackType
from penpine.attack.validator import Validator

SQLI_PAYLOADS = ["'", '"', "')", "';", "' OR '1'='1", "' OR 1=1-- -", "\\"]
SQLI_NUMERIC_PAYLOADS = [" OR 1=1", "1 OR 1=1", "1) OR (1=1"]

SQL_ERROR_SIGNATURES = [
    re.compile(pattern, re.I)
    for pattern in [
        r"you have an error in your sql syntax",
        r"warning.*\bmysqli?_",
        r"valid MySQL result",
        r"PostgreSQL.*ERROR",
        r"pg_query\(\)",
        r"unterminated quoted string",
        r"Microsoft SQL Server",
        r"ODBC SQL Server Driver",
        r"Unclosed quotation mark",
        r"ORA-\d{5}",
        r"quoted string not properly terminated",
        r"SQLite/JDBCDriver",
        r"sqlite3\.OperationalError",
        r"SQL syntax.*error",
    ]
]


class SqliGenerator(PayloadGenerator):
    def __init__(self, payloads=None, numeric_payloads=None):
        self._payloads = list(payloads) if payloads is not None else list(SQLI_PAYLOADS)
        self._numeric = (
            list(numeric_payloads) if numeric_payloads is not None else list(SQLI_NUMERIC_PAYLOADS)
        )

    def generate(self, point, request):
        values = list(self._payloads)
        if is_numeric(point.value):
            values += self._numeric
        for value in values:
            yield TestCase(
                point=point,
                payload=Payload(value, technique="error-based"),
                attack_type=AttackType.SQLI,
            )


class SqliValidator(Validator):
    def __init__(self, signatures=None):
        self._signatures = (
            list(signatures) if signatures is not None else list(SQL_ERROR_SIGNATURES)
        )

    def evaluate(self, test_case, response, baseline=None):
        match = search_signatures(body_text(response), self._signatures)
        if match is None:
            return None
        if baseline is not None and search_signatures(body_text(baseline), self._signatures):
            return None
        return Finding(
            AttackType.SQLI,
            test_case.point,
            test_case.payload,
            Confidence.HIGH,
            f"SQL error signature: {match.group(0)[:80]}",
            request=test_case.request,
            response=response,
        )


SQLI_MODULE = AttackModule(
    "sqli",
    SqliGenerator(),
    SqliValidator(),
    attack_type=AttackType.SQLI,
    applies_to=("param", "form", "json", "multipart", "cookie"),
    description="error-based SQL injection",
)
