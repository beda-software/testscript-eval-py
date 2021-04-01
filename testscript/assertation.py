import logging

from fhirpathpy import evaluate as fhirpath
from jsonpath_ng.ext import parse

from . import operations
from .misc import resolve_string_template


class NotImplementedAssert(Exception):
    pass


def not_implemented_assert(assert_name, _assertation, _result, _resource, _var):
    raise NotImplementedAssert(f"Assert rule {assert_name} is not implemented")


def header_field(_assert_name, assertation, result, _resource, _var):
    operator = assertation["operator"]
    header = assertation["headerField"]
    value = assertation.get("value")
    operations.eval(operator, result.headers.get(header), value)


def response_code(_assert_name, assertation, result, _resource, _var):
    operator = assertation.get("operator", "equals")
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


def response(_assert_name, assertation, result, resource, var):
    response = assertation["response"]
    if response == "okay":
        assert result.status == 200
    elif response == "notFound":
        assert result.status == 404
    elif response == "bad":
        assert result.status == 400
    elif response == "created":
        assert result.status == 201
    else:
        raise Exception(f"Response code {assertation['response']} is not supported")


def validate_profile_id(_assert_name, assertation, result, resource, var):
    logging.warning("Profile validation is not implemented yet")


def compare_to_source_expression(_assert_name, assertation, result, resource, var):
    fixtures = var["--fixtures--"]
    id = assertation["compareToSourceId"]
    fixture = fixtures[id]
    exp = assertation["compareToSourceExpression"]
    val = fhirpath(fixture, exp, {})
    operator = assertation.get("operator", "exists")
    vexp = assertation["expression"]
    res = fhirpath(resource, vexp, {})
    operations.eval(operator, res, val)


def minimum_id(_assert_name, assertation, result, resource, var):
    fixtures = var["--fixtures--"]
    id = assertation["minimumId"]
    fixture = fixtures[id]
    for k, v in fixture.items():
        assert resource[k] == v


def content_type(_assert_name, assertation, result, resource, var):
    operator = assertation.get("operator", "equals")
    value = assertation["contentType"]
    res = result.headers["Content-Type"]
    operations.eval(operator, res, value)


def navigation_links(_assert_name, assertation, result, resource, var):
    assert "link" in resource


assert_rules = {
    "headerField": header_field,
    "responseCode": response_code,
    "resource": resource,
    "path": path,
    "response": response,
    "validateProfileId": validate_profile_id,
    "compareToSourceExpression": compare_to_source_expression,
    "minimumId": minimum_id,
    "contentType": content_type,
    "navigationLinks": navigation_links,
    ######
    # not implemented operations
    ######
    "compareToSourcePath": not_implemented_assert,
}


def eval(assertation, result, resource, var, fixtures):
    # TODO rid of temporary hack
    # pass fixtures as separated context item
    var["--fixtures--"] = fixtures
    logging.warning("Check %s", assertation["description"])
    for assert_name, assert_eval in assert_rules.items():
        if assertation.get("direction") == "request":
            # Skip all request tests
            logging.warning("Skip request validation")
            continue
        if assert_name in assertation:
            assert_eval(assert_name, assertation, result, resource, var)
