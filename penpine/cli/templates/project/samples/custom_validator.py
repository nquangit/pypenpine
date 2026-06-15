"""Custom Validator: inspect the response (and optional baseline) and return a
Finding when the attack succeeded, else None.
    python -m samples.custom_validator
"""
import re

from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload, TestCase
from penpine.attack.validator import Validator
from penpine.core.parse.http_parser import parse_response

_TRACE = re.compile(rb"Traceback \(most recent call last\)")


class StackTraceValidator(Validator):
    """Flag responses leaking a Python stack trace the baseline did not have."""

    def evaluate(self, test_case, response, baseline=None):
        leaked = _TRACE.search(response.body.raw)
        in_baseline = baseline is not None and _TRACE.search(baseline.body.raw)
        if leaked and not in_baseline:
            return Finding(attack_type="error-leak", point=test_case.point,
                           payload=test_case.payload, confidence=Confidence.MEDIUM,
                           evidence="python stack trace in response",
                           request=test_case.request, response=response)
        return None


def _resp(status, body):
    return parse_response(b"HTTP/1.1 %d X\r\nContent-Length: %d\r\n\r\n%s"
                          % (status, len(body), body))


def demo():
    point = InjectionPoint(expr="param:q", kind="param", name="q", value="hi")
    tc = TestCase(point=point, payload=Payload("'"), attack_type="error-leak")
    finding = StackTraceValidator().evaluate(
        tc, _resp(500, b"Traceback (most recent call last): ValueError"))
    print("finding:", finding and finding.evidence)
    return finding


if __name__ == "__main__":
    demo()
