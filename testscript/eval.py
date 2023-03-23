import logging
import os
import re
import urllib

import aiofiles
import yaml
from fhirpathpy import evaluate as fhirpath

from testscript import assertation
from testscript.misc import RawResultAsyncFHIRClient, resolve_string_template


async def setup_fixtures(client: RawResultAsyncFHIRClient, definition):
    fixtures = {}
    for f in definition.get("fixture", []):
        if f.get("autocreate", False):
            raise Exception("Autocreate is not supported")
        if f.get("autodelete", False):
            raise Exception("Autocreate is not supported")
        reference = f["resource"]["reference"]
        fixture_id = f["id"]
        if reference.startswith("#"):
            resource_type, id = reference[1:].split("/")
            fixture = [
                d
                for d in definition["contained"]
                if d["resourceType"] == resource_type and d["id"] == id
            ][0]
            fixtures[fixture_id] = fixture
        elif reference.startswith("file://"):
            root_dir = os.path.dirname(os.path.abspath(__name__))
            parsed_url = urllib.parse.urlsplit(reference)
            file_path = os.path.join(root_dir, parsed_url.netloc) + parsed_url.path
            async with aiofiles.open(file_path) as f:
                content = await f.read()
                fixtures[fixture_id] = yaml.safe_load(content)
        # relative references to FHIR server baseUrl
        elif re.match(r"^[A-Z]", reference):
            _response, resource = await client.execute(reference, method="GET")
            fixtures[fixture_id] = resource
        else:
            raise Exception(f"Reference '{reference}' is not supported")
    return fixtures


def setup_variables(definition, fixtures, env):
    variables = {}
    for var in definition.get("variable", []):
        name = var["name"]
        if "sourceId" in var and "expression" in var:
            context = fixtures[var["sourceId"]]
            variables[name] = fhirpath(context, var["expression"], {})[0]
        else:
            variables[name] = env.get(name, var.get("defaultValue"))
            assert variables[name], f"Missing {name} variable"
    return variables


async def setup(client, definition, fixtures, variables):
    if "setup" not in definition:
        return

    actions = definition["setup"]["action"]
    return await eval_actions(client, actions, fixtures, variables)


async def eval_actions(client, actions, fixtures, variables):
    response = None
    resource = None
    for action in actions:
        if "operation" in action:
            operation = action["operation"]
            logging.warning("%s", operation["description"])
            resource = client.resource(operation["resource"])

            if "targetId" in operation:
                operation_to_exec = fixtures[operation["targetId"]]["id"]
            else:
                operation_to_exec = resolve_string_template(operation.get("params", ""), variables)

            operation_code = operation["type"]["code"]

            if operation_code == "update":
                operation_code = "put"
            elif operation_code in ("read", "search"):
                operation_code = "get"
            elif operation_code == "history":
                operation_code = "get"
                operation_to_exec = operation_to_exec + "/_history"
            elif operation_code == "create":
                operation_code = "post"
            elif operation_code == "populate":
                operation_code = "post"
                operation_to_exec = operation_to_exec + "/$populate"
            elif operation_code == "extract":
                operation_code = "post"
                operation_to_exec = operation_to_exec + "/$extract"

            data = None

            if "sourceId" in operation:
                data = fixtures[operation["sourceId"]]

            response, resource = await resource.execute(
                operation_to_exec, method=operation.get("method", operation_code), data=data
            )

            if "responseId" in operation:
                fixtures[operation["responseId"]] = resource
        else:
            assert response
            assertation.eval(action["assert"], response, resource, variables, fixtures)


async def eval(definition, env):
    logging.warning("Test %s", definition["name"])
    client = RawResultAsyncFHIRClient(
        env["baseUrl"],
        authorization=env["authorization"],
    )

    logging.warning("Loading fixtures")
    fixtures = await setup_fixtures(client, definition)

    logging.warning("Loading variables")
    variables = setup_variables(definition, fixtures, env)

    logging.warning("Setup")
    await setup(client, definition, fixtures, variables)

    logging.warning("Testing")
    for test in definition.get("test", []):
        logging.warning("Test %s, %s", test["name"], test["description"])
        test_actions = test.get("action", [])
        await eval_actions(client, test_actions, fixtures, variables)

    # logging.warning("Teardown")
    # TODO implement teardown
