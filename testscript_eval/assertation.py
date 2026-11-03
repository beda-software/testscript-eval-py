import inspect
import logging
import re
from dataclasses import dataclass, field

from . import misc, operations
from .errors import AssertionFailed, NotImplementedAssert, TestScriptError, TestScriptWarning
from .operations import check

__all__ = ["Context", "NotImplementedAssert", "TestScriptWarning", "evaluate", "eval"]

logger = logging.getLogger("testscript_eval")


@dataclass
class Context:
    """What an assert can see besides the last operation's response."""

    variables: object = field(default_factory=dict)
    fixtures: dict = field(default_factory=dict)
    responses: dict = field(default_factory=dict)
    validator: object = None
    profiles: list = field(default_factory=list)


# http://hl7.org/fhir/assert-response-code-types, and `badRequest`, which scripts use for `bad`
RESPONSE_CODES = {
    "continue": 100, "switchingProtocols": 101, "okay": 200, "created": 201, "accepted": 202,
    "nonAuthoritativeInformation": 203, "noContent": 204, "resetContent": 205,
    "partialContent": 206, "multipleChoices": 300, "movedPermanently": 301, "found": 302,
    "seeOther": 303, "notModified": 304, "useProxy": 305, "temporaryRedirect": 307,
    "permanentRedirect": 308, "bad": 400, "badRequest": 400, "unauthorized": 401,
    "paymentRequired": 402, "forbidden": 403, "notFound": 404, "methodNotAllowed": 405,
    "notAcceptable": 406, "proxyAuthenticationRequired": 407, "requestTimeout": 408,
    "conflict": 409, "gone": 410, "lengthRequired": 411, "preconditionFailed": 412,
    "contentTooLarge": 413, "uriTooLong": 414, "unsupportedMediaType": 415,
    "rangeNotSatisfiable": 416, "expectationFailed": 417, "misdirectedRequest": 421,
    "unprocessableContent": 422, "unprocessable": 422, "upgradeRequired": 426,
    "internalServerError": 500, "notImplemented": 501, "badGateway": 502,
    "serviceUnavailable": 503, "gatewayTimeout": 504, "httpVersionNotSupported": 505,
}  # fmt: skip


def is_request(assertion):
    return assertion.get("direction") == "request"


def _headers(assertion, response):
    """The request's headers for `direction: request`, the response's otherwise."""
    if is_request(assertion):
        return response.request.headers if response.request else None
    return response.headers


def parse_variable_in_string(string, variables):
    return re.sub(r"\$\{([\w-]+)\}", lambda match: misc.to_s(variables[match.group(1)]), string)


def _value(assertion, context):
    value = assertion.get("value")
    return parse_variable_in_string(value, context.variables) if isinstance(value, str) else value


def expression_with_variables(expression, context):
    """An assert expression with its ${variables} resolved (a str, or an Expression dict)."""
    if isinstance(expression, str):
        return parse_variable_in_string(expression, context.variables)
    if isinstance(expression, dict) and isinstance(expression.get("expression"), str):
        return {
            **expression,
            "expression": parse_variable_in_string(expression["expression"], context.variables),
        }
    return expression


def header_field(_assert_name, assertion, response, _resource, context):
    headers = _headers(assertion, response)
    actual = headers.get(assertion["headerField"]) if headers else None
    operations.run(assertion.get("operator", "equals"), actual, _value(assertion, context))


def request_url(_assert_name, assertion, response, _resource, context):
    expected = parse_variable_in_string(assertion["requestURL"], context.variables)
    actual = response.request.url if response.request else None
    operations.run(assertion.get("operator", "equals"), actual, expected)


def request_method(_assert_name, assertion, response, _resource, _context):
    actual = response.request.method if response.request else None
    operations.run(assertion.get("operator", "equals"), actual, assertion["requestMethod"].lower())


def response_code(_assert_name, assertion, response, _resource, _context):
    operations.run(
        assertion.get("operator", "equals"), str(response.status), assertion["responseCode"]
    )


def resource(_assert_name, assertion, _response, resource, _context):
    resource_type = assertion["resource"]
    check(isinstance(resource, dict), "No resource in the response")
    check(
        resource_type == resource.get("resourceType"),
        f"Expected resource {resource_type}, got {resource.get('resourceType')}",
    )


def path(_assert_name, assertion, _response, resource, context):
    path = misc.resolve_string_template(assertion["path"], context.variables)
    logger.debug("Parse %s", path)
    value = _value(assertion, context)
    operator = assertion.get("operator", "exists" if value is None else "equals")
    operations.run(operator, misc.path(resource, path), value)


def response(_assert_name, assertion, response, _resource, _context):
    expected = assertion["response"]
    if expected not in RESPONSE_CODES:
        raise TestScriptError(f"Response code {expected} is not supported")
    status = RESPONSE_CODES[expected]
    operator = assertion.get("operator", "equals")
    if operator not in ("equals", "notEquals"):
        operator = "equals"
    try:
        operations.run(operator, response.status, status)
    except AssertionFailed:
        other = "other than " if operator == "notEquals" else ""
        raise AssertionFailed(
            f"Expected status {other}{status} ({expected}), got {response.status}"
        ) from None


def _fixture(context, id):
    if id not in context.fixtures:
        raise TestScriptError(f"No fixture or response '{id}'")
    return context.fixtures[id]


def compare_to_source_path(_assert_name, assertion, _response, resource, context):
    fixture = _fixture(context, assertion["compareToSourceId"])
    expected = operations.scalar(misc.path(fixture, assertion["compareToSourcePath"]))
    operations.run(
        assertion.get("operator", "equals"), misc.path(resource, assertion["path"]), expected
    )


def compare_to_source_expression(_assert_name, assertion, _response, resource, context):
    fixture = _fixture(context, assertion["compareToSourceId"])
    source_expression = expression_with_variables(assertion["compareToSourceExpression"], context)
    expected = misc.evaluate(fixture, source_expression)
    # Without an expression of its own, the response is read with the source expression
    actual_expression = (
        expression_with_variables(assertion["expression"], context)
        if "expression" in assertion
        else source_expression
    )
    actual = misc.evaluate(resource, actual_expression)
    operator = assertion.get("operator", "equals")
    # Both are collections: equals compares them as a whole
    if operator == "equals":
        return check(actual == expected, f"Got {misc.show(actual)}, expected {misc.show(expected)}")
    operations.run(operator, actual, expected[0] if len(expected) == 1 else expected)


def compare_response_expression_to_value(_assert_name, assertion, _response, resource, context):
    # a path with a value is compared by the "path" rule
    if "expression" not in assertion:
        return
    expression = misc.expression_of(assertion["expression"])
    result = misc.evaluate(resource, expression_with_variables(assertion["expression"], context))
    check(result, f"Expression '{expression}' returned no value")
    if len(result) > 1:
        logger.warning("Expression '%s' returns more than one value", expression)
    operations.run(assertion.get("operator", "equals"), result[0], _value(assertion, context))


def expression(_assert_name, assertion, _response, resource, context):
    # An expression with a value is compared by the "value" rule, one with compareToSourceId
    # by the "compareToSourceExpression" rule, and one with a path by the "path" rule
    if any(key in assertion for key in ("value", "compareToSourceId", "path")):
        return
    # Without a value the expression is a boolean condition: operator "eval",
    # which is also the default (https://hl7.org/fhir/R5/testing.html#assertion-table)
    operator = assertion.get("operator", "eval")
    if operator != "eval":
        raise NotImplementedAssert(f"Operator {operator} without a value is not implemented")
    result = misc.evaluate(resource, expression_with_variables(assertion["expression"], context))
    operations.run(operator, result, None)


def minimum_id(_assert_name, assertion, _response, resource, context):
    id = assertion["minimumId"]
    fixture = _fixture(context, id)
    check(isinstance(resource, dict), "No resource in the response")
    for key, value in fixture.items():
        check(key in resource and resource[key] == value, f"minimumId {id}: {key} does not match")


def content_type(_assert_name, assertion, response, _resource, _context):
    # `json`/`xml` (TestScript formats) match any JSON/XML MIME type,
    # e.g. application/fhir+json;charset=utf-8
    headers = _headers(assertion, response)
    actual = headers.get("Content-Type") if headers else None
    expected = assertion["contentType"]
    operator = assertion.get("operator", "equals")
    if expected.lower() in ("json", "xml") and operator == "equals":
        return check(
            expected.lower() in misc.to_s(actual).lower(),
            f"Content-Type {misc.show(actual)} is not {expected}",
        )
    operations.run(operator, actual.split(";")[0] if actual else None, expected)


def navigation_links(_assert_name, _assertion, _response, resource, _context):
    check(isinstance(resource, dict), "No resource in the response")
    check("link" in resource, "Response has no navigation links")


def resolve_profile(profile_id, profiles):
    # validateProfileId is the id of a TestScript.profile entry; a canonical URL given
    # directly instead (as fhir-frog TestScripts do) is used as is
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("id") == profile_id:
            return profile["reference"]
    if "/" in profile_id:
        return profile_id
    raise TestScriptError(
        f"validateProfileId '{profile_id}' does not match any TestScript.profile id"
    )


async def validate_profile_id(_assert_name, assertion, _response, resource, context):
    profile_url = resolve_profile(assertion["validateProfileId"], context.profiles)
    check(
        isinstance(resource, dict) and "resourceType" in resource,
        f"No resource to validate against {profile_url}",
    )
    errors = context.validator(resource, profile_url)
    if inspect.isawaitable(errors):
        errors = await errors
    check(not errors, f"Validation against {profile_url} failed:\n" + "\n".join(errors))


def _expression_text(expression, context):
    try:
        return misc.expression_of(expression_with_variables(expression, context))
    except (TestScriptError, KeyError):
        return misc.expression_of(expression)


def checked(assert_name, assertion, context):
    """What an assert rule checked, for its failure message,
    e.g. "Expression `issue.count() > 0` on the response"."""
    source = (
        f"fixture/response {assertion['sourceId']}" if assertion.get("sourceId") else "the response"
    )
    direction = "Request" if is_request(assertion) else "Response"
    if assert_name in ("expression", "value"):
        if "expression" not in assertion:
            return None
        if assert_name == "expression" and (
            "value" in assertion or "compareToSourceId" in assertion
        ):
            return None
        return f"Expression `{_expression_text(assertion['expression'], context)}` on {source}"
    if assert_name == "compareToSourceExpression":
        actual = _expression_text(
            assertion.get("expression", assertion["compareToSourceExpression"]), context
        )
        expected = _expression_text(assertion["compareToSourceExpression"], context)
        return (
            f"Expression `{actual}` on {source} compared to "
            f"`{expected}` on {assertion['compareToSourceId']}"
        )
    if assert_name == "path":
        try:
            path = misc.resolve_string_template(assertion["path"], context.variables)
        except (TestScriptError, KeyError):
            path = assertion["path"]
        return f"Path `{path}` on {source}"
    if assert_name == "compareToSourcePath":
        return (
            f"Path `{assertion['path']}` on {source} compared to "
            f"`{assertion['compareToSourcePath']}` on {assertion['compareToSourceId']}"
        )
    return {
        "headerField": f"{direction} header {assertion.get('headerField')}",
        "contentType": f"{direction} Content-Type",
        "response": f"Response status (operator {assertion.get('operator', 'equals')})",
        "responseCode": f"Response status (operator {assertion.get('operator', 'equals')})",
        "requestURL": "Request URL",
        "requestMethod": "Request method",
        "resource": "Resource type",
    }.get(assert_name)


assert_rules = {
    "headerField": header_field,
    "responseCode": response_code,
    "resource": resource,
    "path": path,
    "expression": expression,
    "response": response,
    "compareToSourceExpression": compare_to_source_expression,
    "minimumId": minimum_id,
    "contentType": content_type,
    "navigationLinks": navigation_links,
    "compareToSourcePath": compare_to_source_path,
    "requestURL": request_url,
    "requestMethod": request_method,
    "value": compare_response_expression_to_value,
    "validateProfileId": validate_profile_id,
}


async def evaluate(assertion, response, resource, context):
    """Runs every rule the assert has. Returns a warning message when a warningOnly assert
    fails, None otherwise. `sourceId` points the assert at a fixture, or the response of the
    operation with that responseId."""
    logger.info("%s", assertion.get("description"))
    try:
        if "sourceId" in assertion:
            source_id = assertion["sourceId"]
            response = context.responses.get(source_id, response)
            resource = _fixture(context, source_id)

        for assert_name, rule in assert_rules.items():
            if assert_name not in assertion:
                continue
            try:
                result = rule(assert_name, assertion, response, resource, context)
                if inspect.isawaitable(result):
                    await result
            except AssertionFailed as e:
                # say what was checked: the description alone often does not
                what = checked(assert_name, assertion, context)
                raise type(e)(f"{what}: {e}" if what else str(e)) from None
    except AssertionFailed as e:
        message = f"{assertion.get('description')}: {e}"
        if not assertion.get("warningOnly", False):
            raise type(e)(message) from None
        logger.warning("warningOnly assert failed: %s", message)
        return message
    return None


# The name the module used before
eval = evaluate
