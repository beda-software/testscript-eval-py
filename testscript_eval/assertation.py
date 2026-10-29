import json
import logging
import re
import warnings

from jsonpath_ng.ext import parse

from . import operations
from .misc import fhirpath, resolve_string_template
from .operations import check


class NotImplementedAssert(Exception):
    pass


class TestScriptWarning(UserWarning):
    """A failed warningOnly assert: reported, but does not fail the test script."""


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
    check(isinstance(resource, dict), "No resource in the response")
    check(
        resource_type == resource.get("resourceType"),
        f"Expected resource {resource_type}, got {resource.get('resourceType')}",
    )


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
        check(result.status == 200, f"Expected status 200 (okay), got {result.status}")
    elif response == "notFound":
        check(result.status == 404, f"Expected status 404 (notFound), got {result.status}")
    elif response == "bad":
        check(result.status == 400, f"Expected status 400 (bad), got {result.status}")
    elif response == "created":
        check(result.status == 201, f"Expected status 201 (created), got {result.status}")
    else:
        raise Exception(f"Response code {response} is not supported")


def resolve_profile(profile_id, profiles):
    # validateProfileId is the id of a TestScript.profile entry; a canonical URL given
    # directly instead (as fhir-frog TestScripts do) is used as is
    for profile in profiles:
        if profile.get("id") == profile_id:
            return profile["reference"]
    if "/" in profile_id:
        return profile_id
    raise Exception(f"validateProfileId '{profile_id}' does not match any TestScript.profile id")


async def validate_profile_id(assertation, resource, client, profiles):
    profile_url = resolve_profile(assertation["validateProfileId"], profiles)
    check(
        isinstance(resource, dict) and "resourceType" in resource,
        f"No resource to validate against {profile_url}",
    )
    # Pass the profile both ways: as the $validate `profile` parameter, and in meta.profile,
    # which servers that ignore the parameter (e.g. Aidbox) validate against
    meta = resource.get("meta", {})
    payload = {
        **resource,
        "meta": {**meta, "profile": list(dict.fromkeys([*meta.get("profile", []), profile_url]))},
    }
    response, outcome = await client.execute(
        f"{resource['resourceType']}/$validate",
        method="post",
        data=payload,
        params={"profile": profile_url},
    )
    # No validation happened (auth, $validate unsupported, server error): an engine/infrastructure
    # error, never a check failure, so warningOnly does not hide it
    if response.status in (401, 403, 404, 405) or response.status >= 500:
        raise Exception(
            f"$validate against {profile_url} could not run: status {response.status}: {outcome}"
        )
    if not isinstance(outcome, dict):
        # Non-2xx: the body comes back wrapped in an exception object
        try:
            outcome = json.loads(str(outcome))
        except ValueError:
            outcome = None
    if not isinstance(outcome, dict) or outcome.get("resourceType") != "OperationOutcome":
        raise Exception(
            f"$validate against {profile_url} returned no OperationOutcome "
            f"(status {response.status}): {outcome}"
        )
    errors = [
        f"[{issue.get('severity')}] {', '.join(issue.get('expression', []))}: "
        f"{issue.get('diagnostics') or issue.get('details', {}).get('text', '')}"
        for issue in outcome.get("issue", [])
        if issue.get("severity") in ("error", "fatal")
    ]
    # A 2xx, or a 4xx such as 400/422 with an OperationOutcome, is the validation result
    check(
        response.status < 400 and not errors,
        f"Validation against {profile_url} failed (status {response.status}):\n" + "\n".join(errors),
    )


def parse_variable_in_string(string: str, variables):
    def parse_variable(matchobj: re.Match):
        (var_name,) = matchobj.groups()

        return variables[var_name]

    return re.sub(r"\$\{([\w\-\d]+)+\}", parse_variable, string)


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


def compare_response_expression_to_value(_assert_name, assertation, result, resource, var):
    fixtures = var["--fixtures--"]
    id = assertation.get("sourceId")
    fixture = fixtures[id] if id else resource
    expression = assertation["expression"]
    expression_result = fhirpath(fixture, expression, {})
    check(expression_result, f"Expression '{expression}' returned no value")
    if len(expression_result) > 1:
        logging.warning("Expression '%s' returns more then one value")
    operator = assertation.get("operator", "equals")
    value = assertation["value"]
    if type(value) == str:
        value = parse_variable_in_string(assertation["value"], var)
    operations.eval(operator, expression_result[0], value)


def expression(_assert_name, assertation, result, resource, var):
    # An expression with a value is compared by the "value" rule, and one with
    # compareToSourceId by the "compareToSourceExpression" rule
    if "value" in assertation or "compareToSourceId" in assertation:
        return
    # Without a value the expression is a boolean condition: operator "eval",
    # which is also the default (https://hl7.org/fhir/R5/testing.html#assertion-table)
    operator = assertation.get("operator", "eval")
    if operator != "eval":
        raise NotImplementedAssert(f"Operator {operator} without a value is not implemented")
    fixtures = var["--fixtures--"]
    id = assertation.get("sourceId")
    source = fixtures[id] if id else resource
    operations.eval(operator, fhirpath(source, assertation["expression"], {}), None)


def minimum_id(_assert_name, assertation, result, resource, var):
    fixtures = var["--fixtures--"]
    id = assertation["minimumId"]
    fixture = fixtures[id]
    check(isinstance(resource, dict), "No resource in the response")
    for k, v in fixture.items():
        check(k in resource and resource[k] == v, f"minimumId {id}: {k} does not match")


def content_type(_assert_name, assertation, result, resource, var):
    operator = assertation.get("operator", "equals")
    value = assertation["contentType"]
    res = result.headers["Content-Type"]
    operations.eval(operator, res, value)


def navigation_links(_assert_name, assertation, result, resource, var):
    check(isinstance(resource, dict), "No resource in the response")
    check("link" in resource, "Response has no navigation links")


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
    ######
    # not implemented operations
    ######
    "compareToSourcePath": not_implemented_assert,
    "value": compare_response_expression_to_value,
}


async def eval(assertation, result, resource, var, fixtures, client, profiles):
    # TODO rid of temporary hack
    # pass fixtures as separated context item
    var["--fixtures--"] = fixtures
    logging.warning("%s", assertation["description"])
    if assertation.get("direction") == "request":
        # Skip all request tests
        logging.warning("Skip request validation")
        return
    try:
        for assert_name, assert_eval in assert_rules.items():
            if assert_name in assertation:
                assert_eval(assert_name, assertation, result, resource, var)
        # Validation calls the server, so it is not one of the synchronous assert_rules
        if "validateProfileId" in assertation:
            await validate_profile_id(assertation, resource, client, profiles)
    except AssertionError as e:
        # A failed check of a warningOnly assert is reported and the script goes on; anything
        # else (engine, script or infrastructure errors) is not an AssertionError and still raises
        if not assertation.get("warningOnly", False):
            raise
        logging.warning("warningOnly assert failed: %s: %s", assertation["description"], e)
        warnings.warn(TestScriptWarning(f"{assertation['description']}: {e}"))
