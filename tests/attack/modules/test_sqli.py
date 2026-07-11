import re

from penpine.attack.models import InjectionPoint
from penpine.attack.modules.sqli import (
    SQLI_MODULE,
    SQLI_NUMERIC_PAYLOADS,
    SQLI_PAYLOADS,
    SqliGenerator,
    SqliValidator,
)
from penpine.core.parse.http_parser import parse_response


def pt(value):
    return InjectionPoint("param:x", "param", "x", value)


def resp(body):
    return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))


def test_generator_string_context():
    values = [c.payload.value for c in SqliGenerator().generate(pt("hello"), None)]
    assert values == SQLI_PAYLOADS


def test_generator_numeric_context_adds_payloads():
    values = [c.payload.value for c in SqliGenerator().generate(pt("7"), None)]
    assert values == SQLI_PAYLOADS + SQLI_NUMERIC_PAYLOADS


def test_validator_detects_sql_error():
    tc = next(iter(SqliGenerator().generate(pt("x"), None)))
    f = SqliValidator().evaluate(tc, resp(b"You have an error in your SQL syntax near '''"), None)
    assert f is not None and f.attack_type == "sqli" and f.confidence.name == "HIGH"


def test_validator_clean_response_returns_none():
    tc = next(iter(SqliGenerator().generate(pt("x"), None)))
    assert SqliValidator().evaluate(tc, resp(b"all good"), None) is None


def test_validator_baseline_guard():
    tc = next(iter(SqliGenerator().generate(pt("x"), None)))
    err = resp(b"ORA-00933: SQL command not properly ended")
    assert SqliValidator().evaluate(tc, err, err) is None


def test_custom_payloads_and_signatures():
    cases = list(SqliGenerator(payloads=["X"]).generate(pt("s"), None))
    assert [c.payload.value for c in cases] == ["X"]
    validator = SqliValidator(signatures=[re.compile("CUSTOMSIG")])
    assert validator.evaluate(cases[0], resp(b"... CUSTOMSIG ..."), None) is not None


def test_module_metadata():
    assert SQLI_MODULE.name == "sqli"
    assert SQLI_MODULE.applies("param") and not SQLI_MODULE.applies("path-seg")


def test_validator_detects_multiple_db_errors():
    tc = next(iter(SqliGenerator().generate(pt("x"), None)))
    bodies = [
        b"PostgreSQL query failed: ERROR: syntax error at or near",
        b"Microsoft SQL Server error '80040e14'",
        b"sqlite3.OperationalError: near syntax error",
        b"Unclosed quotation mark after the character string",
    ]
    for body in bodies:
        assert SqliValidator().evaluate(tc, resp(body), None) is not None
