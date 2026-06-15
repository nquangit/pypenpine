"""Transport Interceptor: hook every send/receive on an Engine.

before_send can mutate/log outgoing requests; after_receive can inspect
responses. Attach with Engine(interceptors=[TaggingInterceptor()]).
    python -m samples.custom_interceptor
"""
import asyncio

from penpine.core.message import Request
from penpine.core.parse.http_parser import parse_response
from penpine.transport.interceptor import Interceptor


class TaggingInterceptor(Interceptor):
    """Stamp a header on every outgoing request and count responses."""

    def __init__(self, tag="penpine-sample"):
        self.tag = tag
        self.responses = 0

    async def before_send(self, request):
        return request.set_header("X-Penpine", self.tag)

    async def after_receive(self, request, response):
        self.responses += 1
        return response


def demo():
    interceptor = TaggingInterceptor()
    stamped = asyncio.run(interceptor.before_send(Request.from_url("http://target.example/")))
    resp = parse_response(b"HTTP/1.1 200 X\r\nContent-Length: 0\r\n\r\n")
    asyncio.run(interceptor.after_receive(stamped, resp))
    print("stamped:", b"X-Penpine: penpine-sample" in stamped.serialize())
    print("responses seen:", interceptor.responses)
    return stamped


if __name__ == "__main__":
    demo()
