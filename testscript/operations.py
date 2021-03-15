from funcy.types import is_list, is_mapping


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


def eval(operator, source, value):
    operation = operations[operator]
    operation(operator, source, value)
