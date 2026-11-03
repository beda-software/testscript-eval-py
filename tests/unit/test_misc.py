import os

import pytest
import yaml
from helpers import FIXTURES_DIR

from testscript_eval import misc


def test_keeps_dates_as_strings_and_resolves_include():
    bundle = misc.load_file(os.path.join(FIXTURES_DIR, "resources", "with-include.yaml"))
    assert bundle["timestamp"] == "2023-03-21T10:00:00Z"
    assert bundle["entry"][0]["resource"]["id"] == "test-patient"


def test_still_parses_other_scalars():
    assert misc.load_yaml("a: 1\nb: true\nc: '2020-01-01'\nd: 2020-01-01") == {
        "a": 1,
        "b": True,
        "c": "2020-01-01",
        "d": "2020-01-01",
    }


def test_refuses_arbitrary_python_objects():
    with pytest.raises(yaml.constructor.ConstructorError):
        misc.load_yaml("--- !!python/object:object {}\n")


def test_types_a_root_resource_for_fhirpath():
    outcome = {"resourceType": "OperationOutcome", "issue": []}
    assert misc.fhirpath(outcome, "is(FHIR.OperationOutcome)") == [True]
    assert misc.fhirpath(outcome, "%rootResource.issue.count()") == [0]


def test_evaluates_xpath_paths_on_json():
    bundle = {
        "resourceType": "Bundle",
        "entry": [{"resource": {"resourceType": "Patient", "id": "x"}}],
    }
    assert misc.xpath_to_fhirpath("Bundle/entry/resource/Patient/id", "Bundle") == (
        "entry.resource.ofType(Patient).id"
    )
    assert misc.path(bundle, "Bundle/entry/resource/Patient/id") == ["x"]
    assert misc.path(bundle, "$.entry[0].resource.id") == ["x"]
    assert misc.path(bundle, "entry[0].resource.id") == ["x"]
    expression = {
        "language": "application/xml",
        "expression": "fhir:Bundle/fhir:entry/fhir:resource/fhir:Patient/fhir:id/@value",
    }
    assert misc.evaluate(bundle, expression) == ["x"]
