import pytest

from testscript_eval import AssertionFailed, NotImplementedOperation, operations


def run(operator, source, value=None):
    operations.run(operator, source, value)


def test_checks_equality():
    run("equals", "a", "a")
    with pytest.raises(AssertionFailed, match='expected "b"'):
        run("equals", "a", "b")


def test_compares_values_as_strings():
    run("equals", [True], "true")
    run("equals", 200, "200")
    run("notEquals", "a", "b")
    with pytest.raises(AssertionFailed):
        run("notEquals", ["a"], "a")


def test_checks_comma_separated_alternatives_with_in_contains():
    run("in", "204", "200,204")
    run("notIn", "500", "200,204")
    with pytest.raises(AssertionFailed):
        run("contains", "500", "200,204")
    with pytest.raises(AssertionFailed):
        run("in", None, "200")
    run("contains", ["a", "b"], "b")
    run("notContains", ["a", "b"], "c")


def test_checks_existence():
    run("exists", ["x"])
    for empty in (None, [], {}):
        with pytest.raises(AssertionFailed):
            run("exists", empty)
    run("empty", [])
    with pytest.raises(AssertionFailed):
        run("empty", ["x"])


def test_checks_not_empty():
    run("notEmpty", "Mon, 01 Jan 2024 00:00:00 GMT")
    with pytest.raises(AssertionFailed):
        run("notEmpty", None)


def test_compares_numbers_and_strings():
    run("greaterThan", [10], "9")
    run("lessThan", "a", "b")
    with pytest.raises(AssertionFailed, match="is not greaterThan"):
        run("greaterThan", 1, "2")


def test_checks_a_boolean_fhirpath_result_with_eval():
    run("eval", [True])
    for result in ([False], []):
        with pytest.raises(AssertionFailed):
            run("eval", result)


def test_raises_an_engine_error_for_unknown_operations():
    with pytest.raises(NotImplementedOperation):
        run("bogus", 1, 2)
