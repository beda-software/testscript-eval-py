import json
import os

import pytest

import testscript


def load_test(file_name):
    with open(f"tests/data/{file_name}") as f:
        return json.loads(f.read())


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
        "testscript-example.json",
        "testscript-example-history.json",
        "testscript-example-multisystem.json",
        "testscript-example-readtest.json",
        # "testscript-example-search.json",
        # "testscript-example-update.json",
        "testscript-allergies-questionnaire-populate.json",
    ],
)
async def test_conformance(test_script):
    test = load_test(test_script)
    await testscript.eval(test, env)
