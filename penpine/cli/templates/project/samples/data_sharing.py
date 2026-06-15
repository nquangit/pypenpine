"""Runtime data sharing between two Identities (IDOR pattern).

alice "creates" a resource; the id is captured into a shared Context; bob's
request is rendered with that id — modelling cross-user access testing.
    python -m samples.data_sharing
"""
from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.data.context import Context
from penpine.data.extract import Extract
from penpine.data.identity import Identity


def demo():
    shared = Context()
    alice = Identity("alice", context=shared)
    bob = Identity("bob", context=shared)

    body = b'{"id": 4242, "owner": "alice"}'
    created = parse_response(
        b"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
        % (len(body), body))
    alice.capture(created, [Extract(key="new_id", json="$.id")])

    probe = bob.render(Request.from_raw(
        b"GET /doc/{{new_id}} HTTP/1.1\r\nHost: target.example\r\n\r\n"))
    line = probe.serialize().split(b"\r\n")[0].decode()
    print("bob probes:", line)
    return line


if __name__ == "__main__":
    demo()
