"""Bring-your-own TestCases: skip generation, hand the Runner explicit cases.
    python -m samples.byo_test_cases
"""
from penpine.attack import Runner
from penpine.attack.models import Confidence, Finding, InjectionPoint, Payload, TestCase
from penpine.attack.validator import Validator
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


class ContainsValidator(Validator):
    def __init__(self, needle):
        self.needle = needle.encode()

    def evaluate(self, test_case, response, baseline=None):
        if self.needle in response.body.raw:
            return Finding(attack_type="byo", point=test_case.point,
                           payload=test_case.payload, confidence=Confidence.HIGH,
                           evidence=f"matched {self.needle!r}",
                           request=test_case.request, response=response)
        return None


class _Sender:
    async def send(self, request):
        body = b"unexpected token FOOBAR" if b"FOOBAR" in request.serialize() else b"ok"
        return parse_response(b"HTTP/1.1 200 X\r\nContent-Length: %d\r\n\r\n%s"
                              % (len(body), body))


def demo():
    req = Request.from_url("http://target.example/api?name=alice")
    point = InjectionPoint(expr="param:name", kind="param", name="name", value="alice")
    cases = [TestCase(point=point, payload=Payload("FOOBAR"), attack_type="byo")]
    report = Runner(sender=_Sender()).run_sync(req, test_cases=cases,
                                               validator=ContainsValidator("FOOBAR"))
    print("summary:", report.summary())
    return report


if __name__ == "__main__":
    demo()
