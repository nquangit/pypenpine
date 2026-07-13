import pytest

from penpine.auth.exceptions import LoginError
from penpine.auth.provider import FlowLoginProvider
from penpine.core.message import Request
from penpine.data.extract import Extract
from penpine.flow.flow import Flow
from penpine.flow.step import Step
from tests.flow._fakes import FakeActor, response

_JSON = b"Content-Type: application/json\r\n"


async def test_single_step_flow_login_yields_token():
    engine = FakeActor(script=[response(b'{"access_token":"JWT123"}', headers=_JSON)])
    login = Flow(
        steps=[
            Step(
                "submit",
                request=Request.from_url("http://t/login"),
                capture=[Extract("tok", json="$.access_token")],
            ),
        ]
    )
    provider = FlowLoginProvider(login, token_key="tok")
    session = await provider.login(engine)
    assert session.token == "JWT123"
    assert len(engine.sent) == 1


async def test_multistep_flow_login_threads_csrf():
    engine = FakeActor(
        script=[
            response(b'{"csrf":"C1"}', headers=_JSON),
            response(b'{"access_token":"JWT9"}', headers=_JSON),
        ]
    )
    login = Flow(
        steps=[
            Step(
                "page",
                request=Request.from_url("http://t/login"),
                capture=[Extract("csrf", json="$.csrf")],
            ),
            Step(
                "submit",
                request=Request.from_url("http://t/login?csrf={{csrf}}"),
                capture=[Extract("tok", json="$.access_token")],
            ),
        ]
    )
    provider = FlowLoginProvider(login, token_key="tok")
    session = await provider.login(engine)
    assert session.token == "JWT9"
    assert b"csrf=C1" in engine.sent[1].serialize()  # step 2 used step 1's capture


async def test_failed_login_flow_raises_login_error():
    # 401 with no token -> the required Extract fails -> step fails -> StepError -> LoginError
    engine = FakeActor(script=[response(b"nope", status=b"401 Unauthorized")])
    login = Flow(
        steps=[
            Step(
                "submit",
                request=Request.from_url("http://t/login"),
                capture=[Extract("tok", json="$.access_token")],
            ),
        ]
    )
    provider = FlowLoginProvider(login, token_key="tok")
    with pytest.raises(LoginError):
        await provider.login(engine)


async def test_flow_login_maps_expires_and_data():
    engine = FakeActor(
        script=[response(b'{"access_token":"T","ttl":"3600","uid":"42"}', headers=_JSON)]
    )
    login = Flow(
        steps=[
            Step(
                "submit",
                request=Request.from_url("http://t/login"),
                capture=[
                    Extract("tok", json="$.access_token"),
                    Extract("ttl", json="$.ttl"),
                    Extract("uid", json="$.uid"),
                ],
            ),
        ]
    )
    provider = FlowLoginProvider(login, token_key="tok", expires_key="ttl", data_keys=["uid"])
    session = await provider.login(engine)
    assert session.token == "T"
    assert session.expires_at is not None and session.expires_at > 0
    assert session.data == {"uid": "42"}
