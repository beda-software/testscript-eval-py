from funcy.types import is_list, is_mapping


class NotImplementedOperation(Exception):
    pass


def not_implemented_operation(operation, source, value):
    raise NotImplementedOperation(f"Operation {operation} is not implemented")


def contains(_operation, source, values):
    match = False
    for value in values.split(","):
        match = match or value in source
    assert match, f"{source} not in {values}"


def exists(_operation, source, _value):
    if is_list(source) and len(source) == 0:
        raise Exception("Exist validation issue")
    elif is_mapping(source) and source == {}:
        raise Exception("Exist validation issue")
    elif source is None:
        raise Exception("Exist validation issue")


def equals(_operation, source, value):
    assert source == value, f"Got {source}, expected {value}"


def not_empty(_operation, source, _value):
    assert source is not None


operations = {
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
