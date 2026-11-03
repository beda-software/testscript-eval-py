"""The assert operators (http://hl7.org/fhir/assert-operator-codes).

`source` is what the assert read (a status, header, path or expression result), `value` the
assert's value. Values are compared as strings, as TestScript values are strings ("200", "true").
"""

from .errors import AssertionFailed, NotImplementedOperation
from .misc import show, to_s


def check(condition, message):
    # A failed check is the only thing raised as AssertionFailed, so warningOnly can tell it
    # apart from engine errors; explicit raise, as `python -O` strips bare asserts
    if not condition:
        raise AssertionFailed(message)


def scalar(source):
    """A single-value collection (JSONPath and FHIRPath return collections) is that value."""
    return source[0] if isinstance(source, list) and len(source) == 1 else source


def same(source, value):
    source = scalar(source)
    return source == value or (
        source is not None and value is not None and to_s(source) == to_s(value)
    )


def split(values):
    return [value.strip() for value in to_s(values).split(",")]


def values_of(source):
    return source if isinstance(source, list) else [source]


def blank(source):
    return source is None or (isinstance(source, (list, dict, str)) and len(source) == 0)


def _contains(source, values):
    source = scalar(source)
    if isinstance(source, list):
        return any(same(item, value) for value in split(values) for item in source)
    return any(value in to_s(source) for value in split(values))


def contains(_operator, source, values):
    check(
        source is not None and _contains(source, values),
        f"{show(source)} does not contain {values}",
    )


def not_contains(_operator, source, values):
    check(source is None or not _contains(source, values), f"{show(source)} contains {values}")


def _in(source, values):
    return not blank(source) and all(
        any(same(item, value) for value in split(values)) for item in values_of(source)
    )


def in_(_operator, source, values):
    check(_in(source, values), f"{show(source)} not in {values}")


def not_in(_operator, source, values):
    check(not _in(source, values), f"{show(source)} in {values}")


def exists(_operator, source, _value):
    check(not blank(source) or source == "", "Exist validation issue")


def empty(_operator, source, _value):
    check(blank(source), f"Got {show(source)}, expected no value")


def equals(_operator, source, value):
    check(same(source, value), f"Got {show(scalar(source))}, expected {show(value)}")


def not_equals(_operator, source, value):
    check(
        not same(source, value),
        f"Got {show(scalar(source))}, expected another value than {show(value)}",
    )


def _number(value):
    try:
        return float(to_s(value))
    except ValueError:
        return None


def compare(operator, source, value):
    source = scalar(source)
    left, right = _number(source), _number(value)
    if left is None or right is None:
        left, right = to_s(source), to_s(value)
    check(
        left > right if operator == "greaterThan" else left < right,
        f"{show(source)} is not {operator} {show(value)}",
    )


def not_empty(_operator, source, _value):
    check(not blank(source), "Got no value, expected a non-empty one")


def evaluate(_operator, source, _value):
    # `source` is the FHIRPath result collection of a boolean expression
    check(source == [True], f"Expression evaluated to {show(source)}, expected [true]")


operations = {
    "eval": evaluate,
    "exists": exists,
    "contains": contains,
    "notContains": not_contains,
    "in": in_,
    "notIn": not_in,
    "equals": equals,
    "notEquals": not_equals,
    "greaterThan": compare,
    "lessThan": compare,
    "empty": empty,
    "notEmpty": not_empty,
}


def run(operator, source, value):
    operation = operations.get(operator)
    if operation is None:
        raise NotImplementedOperation(f"Unknown operation {operator}")
    operation(operator, source, value)


# The name the module used before
eval = run
