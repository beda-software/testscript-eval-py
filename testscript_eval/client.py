import json
from dataclasses import dataclass, field
from urllib.parse import urlencode

import aiohttp

from .errors import TestScriptError

JSON_FORMAT = "application/fhir+json"


class Headers:
    """Headers with case-insensitive lookup; a missing header is None."""

    def __init__(self, headers=None):
        self._headers = {}
        for name, value in (headers or {}).items():
            key = self._normalize(name)
            value = ", ".join(value) if isinstance(value, list) else str(value)
            # aiohttp gives repeated headers one by one
            self._headers[key] = f"{self._headers[key]}, {value}" if key in self._headers else value

    @staticmethod
    def _normalize(name):
        return str(name).lower().replace("_", "-")

    def get(self, name, default=None):
        return self._headers.get(self._normalize(name), default)

    def __getitem__(self, name):
        return self.get(name)

    def __contains__(self, name):
        return self._normalize(name) in self._headers

    def to_dict(self):
        return dict(self._headers)


@dataclass
class Request:
    """What was sent, for `direction: request` asserts and requestURL/requestMethod."""

    method: str
    url: str
    headers: Headers


@dataclass
class Response:
    status: int
    headers: Headers
    body: str
    request: Request = field(default=None)


class ErrorBody:
    """The body of a non-2xx response, which is not a resource."""

    def __init__(self, body):
        self.body = body

    def __str__(self):
        return str(self.body)

    def __repr__(self):
        return f"{type(self).__name__}({self.body!r})"


class ResourceNotFound(ErrorBody):
    pass


class OperationOutcome(ErrorBody):
    pass


def mime_type(format):
    """A TestScript format ("json", "xml") or MIME type as the Content-Type/Accept to send.
    Bodies are always JSON: XML is not supported, so requests for XML go out as JSON."""
    if not format or "xml" in str(format).lower() or str(format).lower() == "json":
        return JSON_FORMAT
    return format


class Client:
    """Sends requests to a FHIR server and hands back the raw response along with the parsed
    resource, as asserts check status codes and headers, and resources are kept as plain dicts
    for FHIRPath.

    `authorization` is sent as is in the Authorization header, `headers` with every request.
    Every Response (with its Request) is also passed to `on_response`, e.g. to record requests.
    A given aiohttp `session` is used instead of a session per request.
    """

    def __init__(self, base_url, authorization=None, headers=None, on_response=None, session=None):
        if not base_url:
            raise TestScriptError("FHIR server base URL is not set")
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        if authorization:
            self.headers["Authorization"] = authorization
        self.on_response = on_response
        self.session = session

    def url(self, path, params=None):
        # A full URL (e.g. a Location header) is used as is
        url = (
            path
            if path.startswith(("http://", "https://"))
            else f"{self.base_url}/{path.lstrip('/')}"
        )
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
        return url

    async def execute(
        self,
        path,
        method="get",
        data=None,
        params=None,
        headers=None,
        accept=None,
        content_type=None,
    ):
        """`accept` and `content_type` are TestScript formats ("json", "xml") or MIME types.
        `data` is a resource (sent as JSON), or str/bytes sent as is with `content_type`."""
        url = self.url(path, params)
        request_headers = {**self.headers, "Accept": mime_type(accept), **(headers or {})}
        body = None
        if data is not None:
            if isinstance(data, (str, bytes)):
                body = data
                request_headers["Content-Type"] = content_type or JSON_FORMAT
            else:
                body = json.dumps(data)
                request_headers["Content-Type"] = mime_type(content_type)
        method = method.lower()

        if self.session is not None:
            response = await self._send(self.session, method, url, body, request_headers)
        else:
            async with aiohttp.ClientSession() as session:
                response = await self._send(session, method, url, body, request_headers)
        response.request = Request(method, url, Headers(request_headers))
        if self.on_response:
            self.on_response(response)
        return response, parse_resource(response)

    @staticmethod
    async def _send(session, method, url, body, headers):
        async with session.request(method, url, data=body, headers=headers) as r:
            return Response(r.status, Headers(r.headers), await r.text())


def parse_resource(response):
    """A 2xx body is the resource. Other statuses keep a FHIR resource body (e.g. the
    OperationOutcome of a 422, which asserts check); anything else is wrapped in an ErrorBody."""
    body = response.body
    if body is None or not body.strip():
        return None
    try:
        resource = json.loads(body)
    except ValueError:
        resource = None
    if 200 <= response.status < 300 or (isinstance(resource, dict) and "resourceType" in resource):
        return resource
    return ResourceNotFound(body) if response.status in (404, 410) else OperationOutcome(body)
