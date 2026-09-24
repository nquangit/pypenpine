"""Run a Flow *as an identity*, and read the results (offline, no sockets).

You do NOT `send` a Flow through an identity -- `identity.send(...)` is for a
single Request. Instead you set the identity as the flow's `actor` and call
`run_sync()`. Each step is then sent through that identity (auth/scheme applied),
`{{ }}` placeholders resolve from the identity's `data` (a DataProfile) plus the
flow's own captured context, and you read a `FlowResult` back (not a Response).

    python -m samples.flow_with_identity
"""
from penpine import Flow, Identity, RequestBuilder, Step
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.context import Context
from penpine.data.extract import Extract
from penpine.data.profile import DataProfile


def _resp(body: bytes) -> object:
    head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
    return parse_response(head % (len(body), body))


class _FakeManager:
    """Stands in for the SessionManager an AuthProfile would give you: anything
    with `async send(request)` is a valid actor. Records what it sent."""

    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        if "/balance" in request.target:
            return _resp(b'{"balance": 5000000}')
        if "/transfer" in request.target:
            return _resp(b'{"refId": "TX-1001", "status": "OK"}')
        return _resp(b'{"ok": true}')


def transfer_flow(*, amount, currency, actor=None):
    """Build the flow. Per-transfer params live in the flow's context; the
    account numbers come from the actor's data (see build below)."""

    def confirm(fc):
        # An action step sees `fc.actor` (the identity) and `fc.ctx` (flow context).
        debit = fc.actor.data.require("debit_account")          # from actor.data
        balance = fc.ctx.get("balance")                          # captured in step 1
        print(f"  confirm: {debit} balance={balance} -> transfer {fc.ctx.get('amount')}")
        return None

    return Flow(
        actor=actor,
        context=Context({"amount": amount, "currency": currency}),  # per-run params
        steps=[
            # {{debit_account}} resolves from actor.data
            Step("balance",
                 request=Request.from_url("https://bank.example/accounts/{{debit_account}}/balance"),
                 capture=[Extract("balance", json="$.balance")]),
            Step("confirm", action=confirm),
            # placeholders mix actor.data ({{debit_account}}) and flow context ({{amount}})
            Step("transfer",
                 request=RequestBuilder()
                 .method("POST").url("https://bank.example/transfer")
                 .json({"from": "{{debit_account}}", "to": "{{receive_account}}",
                        "amount": "{{amount}}", "currency": "{{currency}}"})
                 .build(),
                 capture=[Extract("ref", json="$.refId")]),
        ],
    )


def demo():
    # In real use `manager` comes from an AuthProfile (auth + scheme); here a fake.
    quang = Identity(
        "quang",
        manager=_FakeManager(),
        data=DataProfile("quang", {"debit_account": "27784761", "receive_account": "5693841"}),
    )

    result = transfer_flow(amount=1000, currency="VND", actor=quang).run_sync()

    # A Flow returns a FlowResult, not a Response.
    print("summary:", result.summary(), "| ok:", result.ok)
    transfer = result.step("transfer")                          # look up a step by name
    print("transfer step:", transfer.status, transfer.response.status_code)
    print("captured ref:", result.context.get("ref"))
    # Prove the templating pulled from actor.data + context:
    sent = quang.manager.sent[-1]
    print("transfer body:", sent.body.raw.decode())
    return result


if __name__ == "__main__":
    demo()
