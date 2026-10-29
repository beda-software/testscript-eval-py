from funcy.types import is_list, is_mapping


class NotImplementedOperation(Exception):
    pass


def check(condition, message):
    # A failed check is the only thing raised as AssertionError, so warningOnly can tell it
    # apart from engine errors; explicit raise, as `python -O` strips bare asserts
    if not condition:
        raise AssertionError(message)


def not_implemented_operation(operation, source, value):
    raise NotImplementedOperation(f"Operation {operation} is not implemented")


def contains(_operation, source, values):
    match = False
    for value in values.split(","):
        match = match or value in source
    check(match, f"{source} not in {values}")


def exists(_operation, source, _value):
    check(
        not (
            (is_list(source) and len(source) == 0)
            or (is_mapping(source) and source == {})
            or source is None
        ),
        "Exist validation issue",
    )


def equals(_operation, source, value):
    check(source == value, f"Got {source}, expected {value}")


def not_empty(_operation, source, _value):
    check(source is not None, "Got no value, expected a non-empty one")


def evaluate(_operation, source, _value):
    # `source` is the FHIRPath result collection of a boolean expression
    check(source == [True], f"Expression evaluated to {source}, expected [True]")


operations = {
    "eval": evaluate,
    "exists": exists,
    "contains": contains,
    "in": contains,
    "equals": equals,
    "notEmpty": not_empty,
    ######
    # not implemented operations
    ######
    "notEquals": not_implemented_operation,
    "notIn": not_implemented_operation,
    "greaterThan": not_implemented_operation,
    "lessThan": not_implemented_operation,
    "empty": not_implemented_operation,
    "notContains": not_implemented_operation,
}


def eval(operator, source, value):
    operation = operations[operator]
    operation(operator, source, value)
