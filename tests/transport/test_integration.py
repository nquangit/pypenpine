import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import penpine
from penpine.transport.engine import Engine


@pytest.fixture()
def http_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"hello-from-server"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield host, port
    server.shutdown()


def test_real_http_round_trip(http_server):
    host, port = http_server
    req = penpine.Request.from_url(f"http://{host}:{port}/")
    with Engine() as engine:
        resp = engine.send_sync(req)
    assert resp.status_code == 200
    assert resp.body.raw == b"hello-from-server"
