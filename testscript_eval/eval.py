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


async def autocreate_fixtures(client: RawResultAsyncFHIRClient, definition, fixtures, created):
    # `created` is filled one fixture at a time, so if a later create fails
    # the fixtures already on the server are still autodeleted
    for f in definition.get("fixture", []):
        if not f.get("autocreate", False):
            continue
        fixture_id = f["id"]
        fixture = fixtures[fixture_id]
        logging.warning("Autocreate fixture %s", fixture_id)
        # A fixture with an id is created under that id (update as create), so references
        # between fixtures (e.g. Patient/<id>) resolve on the server as written
        if "id" in fixture:
            path, method = f"{fixture['resourceType']}/{fixture['id']}", "put"
        else:
            path, method = fixture["resourceType"], "post"
        response, resource = await client.execute(path, method=method, data=fixture)
        if not 200 <= response.status < 300:
            raise Exception(
                f"Autocreate of fixture '{fixture_id}' failed with status {response.status}: "
                f"{resource}"
            )
        if not resource:
            # No body returned (e.g. Prefer: return=minimal): take the id from Location
            # ([base]/Type/id/_history/vid)
            parts = urlsplit(response.headers["Location"]).path.strip("/").split("/")
            if "_history" in parts:
                parts = parts[: parts.index("_history")]
            resource = {**fixture, "id": parts[-1]}
        # Later references, variables and autodelete must use the server-assigned id
        fixtures[fixture_id] = resource
        created.append(fixture_id)


async def autodelete_fixtures(client: RawResultAsyncFHIRClient, definition, fixtures, created):
    for f in reversed(definition.get("fixture", [])):
        if not f.get("autodelete", False):
            continue
        fixture_id = f["id"]
        # An autocreate fixture whose create did not happen has nothing to delete
        if f.get("autocreate", False) and fixture_id not in created:
            continue
        fixture = fixtures.get(fixture_id)
        if not fixture or "id" not in fixture:
            logging.warning("Autodelete fixture %s skipped: it has no id", fixture_id)
            continue
        logging.warning("Autodelete fixture %s", fixture_id)
        response, _resource = await client.execute(
            f"{fixture['resourceType']}/{fixture['id']}", method="delete"
        )
        if not (200 <= response.status < 300 or response.status in (404, 410)):
            logging.warning(
                "Autodelete of fixture %s failed with status %s", fixture_id, response.status
            )


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
    return await eval_actions(client, actions, fixtures, variables, definition.get("profile", []))


async def teardown(client, definition, fixtures, variables):
    if "teardown" not in definition:
        return
    actions = definition["teardown"]["action"]
    return await eval_actions(client, actions, fixtures, variables, definition.get("profile", []))


async def eval_actions(
    client: RawResultAsyncFHIRClient, actions, fixtures, variables, profiles
):
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
            await assertation.eval(
                action["assert"], response, resource, variables, fixtures, client, profiles
            )


async def eval(definition, env):
    logging.warning("Test %s", definition["name"])
    client = RawResultAsyncFHIRClient(
        env["baseUrl"],
        authorization=env["authorization"],
    )

    logging.warning("Loading fixtures")
    fixtures = await setup_fixtures(client, definition)
    created = []

    try:
        await autocreate_fixtures(client, definition, fixtures, created)
        logging.warning("Loading variables")
        variables = setup_variables(definition, fixtures, env)

        try:
            logging.warning("Setup")
            await setup(client, definition, fixtures, variables)

            logging.warning("Testing")
            for test in definition.get("test", []):
                logging.warning("Test %s, %s", test["name"], test["description"])
                test_actions = test.get("action", [])
                await eval_actions(
                    client, test_actions, fixtures, variables, definition.get("profile", [])
                )
        finally:
            logging.warning("Teardown")
            await teardown(client, definition, fixtures, variables)
    finally:
        await autodelete_fixtures(client, definition, fixtures, created)
