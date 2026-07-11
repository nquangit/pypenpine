from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload, TestCase
from penpine.attack.results import Attempt, Report


def _tc():
    return TestCase(
        point=InjectionPoint("param:a", "param", "a", "1"), payload=Payload("x"), attack_type="t"
    )


def test_attempt_ok_and_found():
    a = Attempt(test_case=_tc(), response=object())
    assert a.ok is True and a.found is False
    f = Finding("t", _tc().point, Payload("x"), Confidence.HIGH, "e")
    assert Attempt(test_case=_tc(), finding=f).found is True
    assert Attempt(test_case=_tc(), error=ValueError("x")).ok is False


def test_report_accessors_and_summary():
    point = InjectionPoint("param:a", "param", "a", "1")
    f = Finding("t", point, Payload("x"), Confidence.HIGH, "e")
    attempts = [
        Attempt(test_case=_tc(), finding=f, response=object()),
        Attempt(test_case=_tc(), error=ValueError("boom")),
        Attempt(test_case=_tc(), response=object()),
    ]
    r = Report(request=object(), attack_type="t", baseline=None, attempts=attempts)
    assert r.findings == [f]
    assert len(r.errors) == 1
    assert r.summary() == {"sent": 3, "failed": 1, "found": 1}
    assert len(r) == 3
    assert list(r)[0] is attempts[0]
