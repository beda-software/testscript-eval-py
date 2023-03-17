import os

import pytest
import yaml

import testscript


def load_test(file_name):
    with open(f"tests/data/{file_name}") as f:
        return yaml.safe_load(f)


env = {
    "baseUrl": os.environ.get("FHIR_SERVER_BASE_URL", "http://devbox:8080"),
    "authorization": "Basic cm9vdDpzZWNyZXQ=",
    "PatientSearchFamilyName": "Peter",
    "PatientSearchGivenName": "Chalmers",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "test_script",
    [
        "testscript-example.yaml",
        "testscript-example-history.yaml",
        "testscript-example-multisystem.yaml",
        "testscript-example-readtest.yaml",
        # "testscript-example-search.yaml",
        # "testscript-example-update.yaml",
        "testscript-allergies-questionnaire-populate.yaml",
    ],
)
async def test_conformance(test_script):
    test = load_test(test_script)
    await testscript.eval(test, env)
