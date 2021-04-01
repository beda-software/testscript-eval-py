import json

import pytest

import testscript


def load_test(file_name):
    with open(f"tests/data/{file_name}") as f:
        return json.loads(f.read())


env = {
    "baseUrl": "http://localhost:8080/fhir",
    "authorization": "Basic cm9vdDpzZWNyZXQ=",
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "test_script",
    [
        "testscript-example-history.json",
        "testscript-example-multisystem.json",
        "testscript-example-readtest.json",
        "testscript-example-search.json",
        "testscript-example-update.json",
        "testscript-example.json",
    ],
)
async def test_conformance(test_script):
    test = load_test(test_script)
    await testscript.eval(test, env)
