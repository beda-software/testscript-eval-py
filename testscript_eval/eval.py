import logging
import os
import re
from urllib.parse import parse_qs, urlparse, urlsplit

import aiofiles
import yaml
from fhirpathpy import evaluate as fhirpath
from yamlinclude import YamlIncludeConstructor

from testscript_eval import assertation
from testscript_eval.misc import RawResultAsyncFHIRClient, resolve_string_template

ROOT_DIR = os.path.dirname(os.path.abspath(__name__))
YamlIncludeConstructor.add_to_loader_class(
    loader_class=yaml.SafeLoader, base_dir=f"{ROOT_DIR}/tests/resources"
)


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
            parsed_url = urlsplit(reference)
            file_path = os.path.join(ROOT_DIR, parsed_url.netloc) + parsed_url.path
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


async def teardown(client, definition, fixtures, variables):
    if "teardown" not in definition:
        return
    actions = definition["teardown"]["action"]
    return await eval_actions(client, actions, fixtures, variables)


async def eval_actions(client: RawResultAsyncFHIRClient, actions, fixtures, variables):
    response = None
    resource = None
    for action in actions:
        if "operation" in action:
            operation = action["operation"]
            logging.warning("%s", operation["description"])
            operation_to_exec = ""
            if "resource" in operation:
                operation_to_exec += operation["resource"]

            if "targetId" in operation:
                operation_to_exec += f"/{fixtures[operation['targetId']]['id']}"
            else:
                operation_to_exec += resolve_string_template(operation.get("params", ""), variables)

            operation_code = operation.get("method", "get")
            if "type" in operation:
                operation_code = operation["type"]["code"]

                if operation_code == "update":
                    operation_code = "put"
                elif operation_code in ("read", "search"):
                    operation_code = "get"
                elif operation_code == "history":
                    operation_code = "get"
                    operation_to_exec += "/_history"
                elif operation_code == "create":
                    operation_code = "post"
                elif operation_code == "populate":
                    operation_code = "post"
                    operation_to_exec += "/$populate"
                elif operation_code == "extract":
                    operation_code = "post"
                    operation_to_exec += "/$extract"

            data = None

            if "sourceId" in operation:
                data = fixtures[operation["sourceId"]]
            operation_to_exec_parse_result = urlparse(operation_to_exec)
            response, resource = await client.execute(
                operation_to_exec_parse_result.path,
                method=operation.get("method", operation_code),
                data=data,
                params=parse_qs(operation_to_exec_parse_result.query),
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

    try:
        logging.warning("Setup")
        await setup(client, definition, fixtures, variables)

        logging.warning("Testing")
        for test in definition.get("test", []):
            logging.warning("Test %s, %s", test["name"], test["description"])
            test_actions = test.get("action", [])
            await eval_actions(client, test_actions, fixtures, variables)
    finally:
        logging.warning("Teardown")
        await teardown(client, definition, fixtures, variables)
