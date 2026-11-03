import asyncio
import json
import logging
import os
import re
import socket
import threading

from aiohttp import web
from yarl import URL

import testscript_eval

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
JSON = {"Content-Type": "application/fhir+json"}

logging.getLogger("testscript_eval").setLevel(logging.CRITICAL)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


BASE = f"http://127.0.0.1:{_free_port()}/fhir"


class Server:
    """A local FHIR server for the tests: stubs answer every matching request (the latest stub
    wins, like WebMock), and every request is recorded. `reset` clears both between tests."""

    def __init__(self):
        self.stubs = []
        self.requests = []
        self.errors = []

    def reset(self):
        self.stubs, self.requests, self.errors = [], [], []

    def stub(self, method, url, status=200, body=None, headers=None, match=None, query=None):
        """`url` is a path from BASE, a full URL or a regex; `match(request)` narrows it."""
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
            headers = {**JSON, **(headers or {})}
        self.stubs.insert(0, (method.upper(), url, query, match, status, body or "", headers or {}))

    @staticmethod
    def _matches(url, query, request_url):
        if isinstance(url, re.Pattern):
            return bool(url.search(str(request_url)))
        expected = URL(url if url.startswith("http") else f"{BASE}{url}")
        if query is not None:
            expected = expected.with_query(query)
        return expected.with_query(sorted(expected.query.items())) == request_url.with_query(
            sorted(request_url.query.items())
        )

    async def handle(self, http_request):
        body = await http_request.text()
        url = URL(BASE).with_path(http_request.path).with_query(http_request.query)
        request = {
            "method": http_request.method,
            "url": url,
            "headers": dict(http_request.headers),
            "body": body,
        }
        self.requests.append(request)
        for method, stub_url, query, match, status, response_body, headers in self.stubs:
            if method != request["method"] or not self._matches(stub_url, query, url):
                continue
            if match and not match(request):
                continue
            return web.Response(status=status, text=response_body, headers=headers)
        self.errors.append(f"Unexpected request {request['method']} {url}")
        return web.Response(status=599, text="no stub")

    def made(self, method, url, query=None, match=None):
        """The recorded requests matching method and url (and `match`)."""
        return [
            r
            for r in self.requests
            if r["method"] == method.upper()
            and self._matches(url, query, r["url"])
            and (match is None or match(r))
        ]


SERVER = Server()


def _serve(started):
    loop = asyncio.new_event_loop()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", SERVER.handle)
    runner = web.AppRunner(app, access_log=None)
    loop.run_until_complete(runner.setup())
    url = URL(BASE)
    loop.run_until_complete(web.TCPSite(runner, url.host, url.port).start())
    started.set()
    loop.run_forever()


_started = threading.Event()
threading.Thread(target=_serve, args=(_started,), daemon=True).start()
_started.wait(5)


def run_script(definition, env=None, **options):
    options.setdefault("root_dir", FIXTURES_DIR)
    if env is None:
        env = {"baseUrl": BASE, "authorization": "Basic dGVzdDp0ZXN0"}
    return asyncio.run(testscript_eval.eval(definition, env, **options))


def script(**parts):
    return {"resourceType": "TestScript", "name": "spec", **parts}


def operation(**fields):
    return {"operation": fields}


def assertion(**fields):
    return {"assert": {"description": "check", **fields}}
