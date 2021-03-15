import json
import logging

import pytest

from testscript import assertation
from testscript.misc import RawResultAsyncFHIRClient, resolve_string_template


def load_test(file_name):
    with open(file_name) as f:
        return json.loads(f.read())


def load_secrets():
    with open(".secret.json") as f:
        return json.loads(f.read())


async def eval_test(definition, var):
    logging.warning("Test %s", definition["name"])
    client = RawResultAsyncFHIRClient(
        var["baseUrl"],
        authorization=var["authorization"],
    )
    operation = definition["test"]["action"][0]["operation"]
    operation_to_exec = resolve_string_template(operation["params"], var)

    resource = client.resource(operation["resource"])

    result, resource = await resource.execute(
        operation_to_exec, method=operation.get("method", "get")
    )

    for assertation_definition in definition["test"]["action"][1:]:
        assertation.eval(assertation_definition["assert"], result, resource, var)


@pytest.mark.asyncio
async def test_conformance():
    secrets = load_secrets()
    test_name = secrets["testName"]
    test = load_test(test_name)
    await eval_test(test, secrets)
