import json

import aiohttp
from fhirpy import AsyncFHIRClient
from fhirpy.base.exceptions import OperationOutcome, ResourceNotFound
from fhirpy.base.utils import AttrDict
from funcy.strings import re_all
from funcy.types import is_list, is_mapping


def walk_dict(d):
    for k, v in d.items():
        if is_list(v):
            d[k] = [walk_dict(vi) for vi in v]
        elif is_mapping(v) and "_value" not in v:
            d[k] = walk_dict(v)
        elif is_mapping(v) and "_value" in v:
            d[k] = v["_value"]
    return d


async def get_resource(r):
    if 200 <= r.status < 300:
        data = await r.text()
        if data:
            return json.loads(data, object_hook=AttrDict)
        return None

    if r.status == 404 or r.status == 410:
        return ResourceNotFound(await r.text())

    return OperationOutcome(await r.text())


class RawResultAsyncFHIRClient(AsyncFHIRClient):
    async def _do_request(self, method, path, data=None, params=None):
        headers = self._build_request_headers()
        url = self._build_request_url(path, params)
        async with aiohttp.request(method, url, json=data, headers=headers) as r:
            return r, await get_resource(r)


def resolve_string_template(i, env):
    if not isinstance(i, str):
        return i
    exprs = re_all(r"(?P<var>\${[\S\s]+?})", i)
    vs = {}
    for exp in exprs:
        data = env[exp["var"][2:-1]]
        vs[exp["var"]] = data
    res = i
    for k, v in vs.items():
        res = res.replace(k, v)

    return res
