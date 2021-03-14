import json
import logging

import aiohttp
import pytest
from fhirpy import AsyncFHIRClient
from fhirpy.base.exceptions import OperationOutcome, ResourceNotFound
from fhirpy.base.utils import AttrDict
from funcy.strings import re_all
from funcy.types import is_list, is_mapping
from jsonpath_ng.ext import parse


async def get_resource(r):
    if 200 <= r.status < 300:
        data = await r.text()
        return json.loads(data, object_hook=AttrDict)

    if r.status == 404 or r.status == 410:
        return ResourceNotFound(await r.text())

    return OperationOutcome(await r.text())


class RawResultAsyncFHIRClient(AsyncFHIRClient):
    async def _do_request(self, method, path, data=None, params=None):
        headers = self._build_request_headers()
        url = self._build_request_url(path, params)
        async with aiohttp.request(method, url, json=data, headers=headers) as r:
            return r, await get_resource(r)


def load_test(file_name):
    with open(file_name) as f:
        return json.loads(f.read())


def load_secrets():
    with open(".secret.json") as f:
        return json.loads(f.read())


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


class NotImplementedAssert(Exception):
    pass


def not_implemented_assert(assert_name, _assertation, _result, _resource, _var):
    raise NotImplementedAssert(f"Assert rule {assert_name} is not implemented")


class NotImplementedOperation(Exception):
    pass


def not_implemented_operation(operation, source, value):
    raise NotImplementedOperation(f"Operation {operation} is not implemented")


def contains(_operation, source, value):
    assert value in source


def exists(_operation, source, _value):
    if is_list(source) and len(source) == 0:
        raise Exception("Exist validation issue")
    elif is_mapping(source) and source == {}:
        raise Exception("Exist validation issue")
    elif source is None:
        raise Exception("Exist validation issue")


operations = {
    "exists": exists,
    "contains": contains,
    "in": contains,
    "equals": not_implemented_operation,
    "notEquals": not_implemented_operation,
    "notIn": not_implemented_operation,
    "greaterThan": not_implemented_operation,
    "lessThan": not_implemented_operation,
    "empty": not_implemented_operation,
    "notEmpty": not_implemented_operation,
    "notContains": not_implemented_operation,
}


def perform_check(operator, source, value):
    operation = operations[operator]
    operation(operator, source, value)


def header_field(_assert_name, assertation, result, _resource, _var):
    if assertation["direction"] == "request":
        # Skip all request tests
        return
    operator = assertation["operator"]
    header = assertation["headerField"]
    value = assertation["value"]
    perform_check(operator, result.headers[header], value)


def response_code(_assert_name, assertation, result, _resource, _var):
    operator = assertation["operator"]
    value = assertation["responseCode"]
    perform_check(operator, str(result.status), value)


def resource(_assert_name, assertation, _result, resource, _var):
    resource_type = assertation["resource"]
    if assertation.get("operator", "equals") == "equals":
        assert resource_type == resource["resourceType"]
    else:
        assert resource_type == resource["resourceType"]


def path(_assert_name, assertation, result, resource, var):
    path = resolve_string_template(assertation["path"], var)
    logging.warning("Parse %s", path)
    jsonpath_expr = parse(path)
    res = jsonpath_expr.find(resource)
    operator = assertation.get("operator", "exists")
    value = assertation.get("value")
    perform_check(operator, res, value)


assert_rules = {
    "headerField": header_field,
    "responseCode": response_code,
    "resource": resource,
    "path": path,
    "compareToSourcePath": not_implemented_assert,
    "contentType": not_implemented_assert,
    "minimumId": not_implemented_assert,
    "navigationLinks": not_implemented_assert,
    "response": not_implemented_assert,
    "validateProfileId": not_implemented_assert,
}


def eval_assertation(assertation, result, resource, var):
    logging.warning("Check %s", assertation["description"])
    for assert_name, assert_eval in assert_rules.items():
        if assert_name in assertation:
            assert_eval(assert_name, assertation, result, resource, var)


async def eval_test(definition, var):
    logging.warning("Test %s", definition["name"])
    client = RawResultAsyncFHIRClient(
        var["baseUrl"],
        authorization=var["authorization"],
    )
    operation = definition["test"]["action"][0]["operation"]
    operation_to_exec = resolve_string_template(operation["params"], var)

    resource = client.resource(operation["resource"])

    result, resource = await resource.execute(
        operation_to_exec, method=operation.get("method", "get")
    )

    for assertation in definition["test"]["action"][1:]:
        eval_assertation(assertation["assert"], result, resource, var)


@pytest.mark.asyncio
async def test_conformance():
    secrets = load_secrets()
    test_name = secrets["testName"]
    test = load_test(test_name)
    await eval_test(test, secrets)
