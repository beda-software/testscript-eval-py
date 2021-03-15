import json

import pytest

import testscript


def load_test(file_name):
    with open(file_name) as f:
        return json.loads(f.read())


def load_secrets():
    with open(".secret.json") as f:
        return json.loads(f.read())


@pytest.mark.asyncio
async def test_conformance():
    secrets = load_secrets()
    test_name = secrets["testName"]
    test = load_test(test_name)
    await testscript.eval(test, secrets)
