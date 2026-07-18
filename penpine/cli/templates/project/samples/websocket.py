"""WebSocket sample: client, attack, and a flow.

Offline-safe: set WS_URL to run against a real server, e.g.
    WS_URL=wss://target:6363/ws python -m samples.websocket
With WS_URL unset it prints usage and exits (so the offline test passes).
"""

import os

from penpine import AttackType, run_ws_attack_sync, ws_connect_sync
from penpine.data import Context, Extract
from penpine.flow import Flow, ws_close, ws_open, ws_send

WS_URL = os.environ.get("WS_URL")


def main():
    if not WS_URL:
        print("set WS_URL=wss://host/ws to run the WebSocket sample")
        return

    # 1) direct client
    ws = ws_connect_sync(WS_URL)
    try:
        ws.send_text_sync('{"action":"ping"}')
        print("reply:", ws.recv_sync().data)
    finally:
        ws.close_sync()

    # 2) attack (fuzz every JSON field of a message)
    report = run_ws_attack_sync(WS_URL, '{"action":"get","id":"1"}', AttackType.FUZZ)
    print("fuzz summary:", report.summary())

    # 3) flow: open -> send (templated) -> capture -> close
    result = Flow([
        ws_open("connect", WS_URL),
        ws_send("get", '{"action":"get","id":"{{id}}"}', capture=[Extract("reply", regex=r"(.+)")]),
        ws_close("bye"),
    ], context=Context({"id": "1"})).run_sync()
    print("flow steps:", [s.status for s in result.steps])


if __name__ == "__main__":
    main()
