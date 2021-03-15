import logging

from jsonpath_ng.ext import parse

from . import operations
from .misc import resolve_string_template


class NotImplementedAssert(Exception):
    pass


def not_implemented_assert(assert_name, _assertation, _result, _resource, _var):
    raise NotImplementedAssert(f"Assert rule {assert_name} is not implemented")


def header_field(_assert_name, assertation, result, _resource, _var):
    if assertation["direction"] == "request":
        # Skip all request tests
        return
    operator = assertation["operator"]
    header = assertation["headerField"]
    value = assertation["value"]
    operations.eval(operator, result.headers[header], value)


def response_code(_assert_name, assertation, result, _resource, _var):
    operator = assertation["operator"]
    value = assertation["responseCode"]
    operations.eval(operator, str(result.status), value)


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
    operations.eval(operator, res, value)


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


def eval(assertation, result, resource, var):
    logging.warning("Check %s", assertation["description"])
    for assert_name, assert_eval in assert_rules.items():
        if assert_name in assertation:
            assert_eval(assert_name, assertation, result, resource, var)
