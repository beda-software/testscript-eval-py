import json

import pytest

import testscript


def load_test(file_name):
    with open(f"tests/data/{file_name}") as f:
        return json.loads(f.read())


env = {
    "baseUrl": "http://localhost:8088",
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
