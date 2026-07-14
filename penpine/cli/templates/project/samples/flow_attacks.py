"""Flow-structural attacks via FlowRunner (offline, no sockets).

SkipStepModule drops each step and checks whether the goal step still succeeds
(broken access control). Pass a module CLASS (no parens), or a list of modules.
    python -m samples.flow_attacks
"""
from penpine import Flow, FlowRunner, Step
from penpine.attack.flow import SkipStepModule
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response


class _FakeActor:
    def __init__(self, name="user"):
        self.name = name
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return parse_response(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndone")


def demo():
    flow = Flow(
        actor=_FakeActor(),
        steps=[
            Step("login", request=Request.from_url("http://target.example/login")),
            Step("action", request=Request.from_url("http://target.example/action")),
            Step("confirm", request=Request.from_url("http://target.example/confirm")),
        ],
    )
    report = FlowRunner().run_sync(flow, module=SkipStepModule)  # class, no parens
    print("skip-step:", report.summary())
    for finding in report.findings:
        print(f"  {finding.attack_type} {finding.target} -> {finding.evidence}")
    return report


if __name__ == "__main__":
    demo()
