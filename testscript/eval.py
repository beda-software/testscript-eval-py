import logging

from testscript import assertation
from testscript.misc import RawResultAsyncFHIRClient, resolve_string_template


async def eval(definition, env):
    logging.warning("Test %s", definition["name"])
    client = RawResultAsyncFHIRClient(
        env["baseUrl"],
        authorization=env["authorization"],
    )
    operation = definition["test"]["action"][0]["operation"]
    operation_to_exec = resolve_string_template(operation["params"], env)

    resource = client.resource(operation["resource"])

    result, resource = await resource.execute(
        operation_to_exec, method=operation.get("method", "get")
    )

    for assertation_definition in definition["test"]["action"][1:]:
        assertation.eval(assertation_definition["assert"], result, resource, env)
