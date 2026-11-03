import base64
import logging
import os
import re
from urllib.parse import parse_qs, urlsplit

from . import assertation, misc
from .client import Client
from .errors import FixtureRejected, TestScriptError
from .server_validator import ServerValidator
from .variables import Variables

logger = logging.getLogger("testscript_eval")

# TestScript operation type codes (http://terminology.hl7.org/CodeSystem/testscript-operation-codes)
# with their HTTP method and the path suffix the operation adds. An operation's own `method`
# wins; other codes are taken as the HTTP method itself
OPERATION_TYPES = {
    "read": ("get", ""),
    "vread": ("get", ""),
    "update": ("put", ""),
    "updateCreate": ("put", ""),
    "patch": ("patch", ""),
    "delete": ("delete", ""),
    "deleteCondSingle": ("delete", ""),
    "deleteCondMultiple": ("delete", ""),
    "history": ("get", "/_history"),
    "create": ("post", ""),
    "search": ("get", ""),
    "batch": ("post", ""),
    "transaction": ("post", ""),
    "capabilities": ("get", "metadata"),
    "validate": ("post", "/$validate"),
    # a named operation, given in `params` (e.g. `$validate-e-rezept`)
    "operation": ("post", ""),
    "populate": ("post", "/$populate"),
    "extract": ("post", "/$extract"),
}

FILE_REFERENCE = re.compile(r"\.(json|ya?ml)$", re.IGNORECASE)


def default_env():
    return {
        "baseUrl": os.environ.get("FHIR_SERVER_BASE_URL"),
        "authorization": os.environ.get("FHIR_SERVER_AUTHORIZATION"),
    }


def _ok(response):
    return 200 <= response.status < 300


def _location_parts(location):
    parts = [part for part in urlsplit(location).path.split("/") if part]
    if "_history" in parts:
        parts = parts[: parts.index("_history")]
    return parts


def _is_transaction(fixture):
    return fixture.get("resourceType") == "Bundle" and fixture.get("type") in (
        "transaction",
        "batch",
    )


def _is_binary(data):
    return isinstance(data, dict) and data.get("resourceType") == "Binary" and "data" in data


class Evaluator:
    """Runs one TestScript: loads fixtures, autocreates them, then runs setup, tests and
    teardown, and finally autodeletes fixtures.

    `root_dir` resolves file fixture references, `include_dir` the `!include` tags of YAML
    fixtures. `client` defaults to a Client for env baseUrl/authorization, `validator`
    (validateProfileId asserts) to a ServerValidator, which runs $validate on that server.
    `client` and `validator` can be swapped between phases.
    """

    def __init__(
        self, definition, env=None, root_dir=None, include_dir=None, client=None, validator=None
    ):
        self.definition = definition
        self.env = dict(default_env() if env is None else env)
        self.root_dir = root_dir or os.getcwd()
        self.include_dir = include_dir or os.path.join(self.root_dir, "tests", "resources")
        self._client = client
        self.validator = validator
        self.warnings = []
        self.fixtures = None
        self.variables = None
        self._created = []
        # responseId => Response of that operation; its resource also goes in fixtures
        self._responses = {}
        self._last = None
        self.last_resource = None
        self._finished = False
        self._fixture_definitions = None
        self._profiles = None

    @property
    def tests(self):
        return self.definition.get("test", [])

    @property
    def client(self):
        if self._client is None:
            self._client = Client(
                self.env.get("baseUrl"), authorization=self.env.get("authorization")
            )
        return self._client

    @client.setter
    def client(self, client):
        self._client = client

    def _validator(self):
        return self.validator or ServerValidator(self.client)

    async def run(self):
        """Runs the whole script and returns the messages of failed warningOnly asserts."""
        try:
            await self.start()
            for test in self.tests:
                await self.run_test(test)
            return self.warnings
        finally:
            await self.finish()

    async def start(self):
        """Loads and autocreates fixtures, then runs setup. When it raises, `finish` still
        cleans up whatever was created."""
        logger.info("Test %s", self.definition.get("name"))
        logger.info("Loading fixtures")
        self.fixtures = await self._setup_fixtures()
        await self._autocreate_fixtures()
        # Variables are evaluated where they are used, as they may read responses of setup operations
        self.variables = Variables(self.definition.get("variable", []), self.env, self)

        logger.info("Setup")
        await self._eval_actions(self.definition.get("setup", {}).get("action", []))

    async def run_test(self, test):
        """Runs one of the script's tests; returns the messages of its failed warningOnly asserts."""
        logger.info("Test %s, %s", test.get("name"), test.get("description"))
        count = len(self.warnings)
        await self._eval_actions(test.get("action", []))
        return self.warnings[count:]

    async def finish(self):
        """Runs teardown (when `start` got as far as variables), then autodeletes fixtures."""
        if self._finished:
            return
        self._finished = True
        try:
            if self.variables is not None:
                logger.info("Teardown")
                await self._eval_actions(self.definition.get("teardown", {}).get("action", []))
        finally:
            if self.fixtures is not None:
                await self._autodelete_fixtures()

    def source(self, id):
        """The resource of a response (by its responseId) or a fixture, for variables and asserts."""
        if id not in self.fixtures:
            raise TestScriptError(f"No fixture or response '{id}'")
        return self.fixtures[id]

    def response_of(self, id=None):
        """The Response of an operation by its responseId, or the last one without an id."""
        if id is None:
            return self._last
        if id not in self._responses:
            raise TestScriptError(f"No response '{id}'")
        return self._responses[id]

    # Fixtures

    @property
    def fixture_definitions(self):
        # Fixtures without an id (which nothing can refer to) get one, so each is kept on its own
        if self._fixture_definitions is None:
            self._fixture_definitions = [
                fixture if "id" in fixture else {**fixture, "id": f"fixture-{index + 1}"}
                for index, fixture in enumerate(self.definition.get("fixture", []))
            ]
        return self._fixture_definitions

    async def _setup_fixtures(self):
        # A fixture without a resource (only an id, e.g. a placeholder a responseId fills) is None
        fixtures = {}
        for fixture in self.fixture_definitions:
            reference = fixture.get("resource", {}).get("reference")
            fixtures[fixture["id"]] = (
                await self._load_fixture(fixture["id"], reference) if reference else None
            )
        return fixtures

    async def _load_fixture(self, fixture_id, reference):
        if reference.startswith("#"):
            resource_type, id = reference[1:].split("/")
            for resource in self.definition.get("contained", []):
                if resource.get("resourceType") == resource_type and resource.get("id") == id:
                    return resource
            raise TestScriptError(f"Contained resource '{reference}' is not found")
        # files: `file://examples/x.json`, or a path (`/examples/x.json`, `../Fixtures/x.yaml`,
        # `x.json`), all from the root directory
        if reference.startswith("file://") or FILE_REFERENCE.search(reference):
            relative = reference.removeprefix("file://").removeprefix("/")
            path = os.path.normpath(os.path.join(self.root_dir, relative))
            if not os.path.exists(path):
                raise TestScriptError(
                    f"Fixture '{fixture_id}': file {reference} is not found ({path})"
                )
            return misc.load_file(path, include_dir=self.include_dir)
        # resources on the server: relative references to baseUrl (`Patient/example`) or absolute URLs
        if re.match(r"^([A-Z]|https?://)", reference):
            return await self._read_server_fixture(fixture_id, reference)
        raise TestScriptError(f"Reference '{reference}' is not supported")

    async def _read_server_fixture(self, fixture_id, reference):
        response, resource = await self.client.execute(reference, method="get")
        if _ok(response) and isinstance(resource, dict):
            return resource
        raise FixtureRejected(
            f"Fixture '{fixture_id}': {reference} could not be read from the server "
            f"(status {response.status}); the script expects it to exist there"
        )

    async def _autocreate_fixtures(self):
        # `_created` is filled one fixture at a time, so if a later create fails
        # the fixtures already on the server are still autodeleted
        definitions = [d for d in self.fixture_definitions if d.get("autocreate", False)]
        for definition in definitions:
            if not isinstance(self.fixtures[definition["id"]], dict):
                raise TestScriptError(f"Autocreate fixture '{definition['id']}' has no resource")

        # Fixtures with ids go in one transaction, so references between them resolve whatever
        # their order, even in cycles, on servers that check references
        together = [d for d in definitions if self._is_transactable(self.fixtures[d["id"]])]
        if not (len(together) > 1 and await self._autocreate_together(together)):
            together = []

        for definition in definitions:
            if definition in together:
                continue
            fixture_id = definition["id"]
            fixture = self.fixtures[fixture_id]
            logger.info("Autocreate fixture %s", fixture_id)
            if _is_transaction(fixture):
                await self._autocreate_bundle(fixture_id, fixture)
                continue

            # A fixture with an id is created under that id (update as create), so references
            # between fixtures (e.g. Patient/<id>) resolve on the server as written
            if "id" in fixture:
                path, method = f"{fixture['resourceType']}/{fixture['id']}", "put"
            else:
                path, method = fixture["resourceType"], "post"
            response, resource = await self.client.execute(path, method=method, data=fixture)
            if not _ok(response):
                raise FixtureRejected(
                    f"Autocreate of fixture '{fixture_id}' failed with status {response.status}: "
                    f"{resource}"
                )
            # Later references, variables and autodelete must use the server-assigned id
            self.fixtures[fixture_id] = resource or {
                **fixture,
                "id": self._created_id(response, fixture, fixture_id),
            }
            self._created.append(fixture_id)

    @staticmethod
    def _is_transactable(fixture):
        return "id" in fixture and not _is_transaction(fixture)

    async def _autocreate_together(self, definitions):
        """PUTs the fixtures in one transaction Bundle. False when the server does not take it
        (e.g. no transaction support, or a fixture it rejects): they are then created one by one."""
        logger.info(
            "Autocreate fixtures %s in a transaction", ", ".join(d["id"] for d in definitions)
        )
        entries = []
        for definition in definitions:
            fixture = self.fixtures[definition["id"]]
            url = f"{fixture['resourceType']}/{fixture['id']}"
            entries.append({"resource": fixture, "request": {"method": "PUT", "url": url}})
        bundle = {"resourceType": "Bundle", "type": "transaction", "entry": entries}
        response, resource = await self.client.execute("", method="post", data=bundle)
        if not (_ok(response) and isinstance(resource, dict)):
            logger.warning(
                "Transaction of the fixtures failed with status %s, creating them one by one",
                response.status,
            )
            return False

        response_entries = resource.get("entry", [])
        for index, definition in enumerate(definitions):
            entry = response_entries[index] if index < len(response_entries) else {}
            created = entry.get("resource")
            if isinstance(created, dict) and created.get("resourceType"):
                self.fixtures[definition["id"]] = created
            self._created.append(definition["id"])
        return True

    async def _autocreate_bundle(self, fixture_id, fixture):
        """A transaction or batch Bundle is posted to the server root, which creates its entries;
        the fixture becomes the response Bundle, and autodelete deletes the entries' resources."""
        response, resource = await self.client.execute("", method="post", data=fixture)
        if not (_ok(response) and isinstance(resource, dict)):
            raise FixtureRejected(
                f"Autocreate of fixture '{fixture_id}' failed with status {response.status}: "
                f"{resource}"
            )
        self.fixtures[fixture_id] = resource
        self._created.append(fixture_id)

    @staticmethod
    def _bundle_locations(bundle):
        """The Type/id of every resource a transaction or batch response reports as created."""
        locations = []
        for entry in bundle.get("entry", []):
            location = entry.get("response", {}).get("location")
            if location:
                locations.append("/".join(_location_parts(location)[-2:]))
        return locations

    @staticmethod
    def _created_id(response, fixture, fixture_id):
        # No body returned (e.g. Prefer: return=minimal): take the id from Location
        # ([base]/Type/id/_history/vid), which an update as create may leave out
        location = response.headers.get("Location")
        if location is None and "id" in fixture:
            return fixture["id"]
        if location is None:
            raise TestScriptError(
                f"Autocreate of fixture '{fixture_id}' returned neither a body nor a Location"
            )
        return _location_parts(location)[-1]

    async def _autodelete_fixtures(self):
        for definition in reversed(self.fixture_definitions):
            if not definition.get("autodelete", False):
                continue
            fixture_id = definition["id"]
            # An autocreate fixture whose create did not happen has nothing to delete
            if definition.get("autocreate", False) and fixture_id not in self._created:
                continue
            targets = self._autodelete_targets(definition, self.fixtures.get(fixture_id))
            if not targets:
                logger.warning("Autodelete fixture %s skipped: it has no id", fixture_id)
                continue
            logger.info("Autodelete fixture %s", fixture_id)
            for target in reversed(targets):
                await self._delete(fixture_id, target)

    def _autodelete_targets(self, definition, fixture):
        if not isinstance(fixture, dict):
            return []
        # an autocreated transaction: the fixture is the response Bundle
        if (
            definition.get("autocreate", False)
            and fixture.get("resourceType") == "Bundle"
            and fixture.get("type") in ("transaction-response", "batch-response")
        ):
            return self._bundle_locations(fixture)
        return [f"{fixture['resourceType']}/{fixture['id']}"] if "id" in fixture else []

    async def _delete(self, fixture_id, target):
        response, _resource = await self.client.execute(target, method="delete")
        if not (_ok(response) or response.status in (404, 410)):
            logger.warning(
                "Autodelete of fixture %s (%s) failed with status %s",
                fixture_id,
                target,
                response.status,
            )

    # Actions

    async def _eval_actions(self, actions, response=None, resource=None):
        for action in actions:
            if "common" in action:
                response, resource = await self._eval_common(action["common"], response, resource)
            elif "operation" in action:
                response, resource = await self._execute_operation(action["operation"])
            else:
                assertion = action["assert"]
                if response is None and "sourceId" not in assertion:
                    raise TestScriptError("Assert has no preceding operation response")
                warning = await assertation.evaluate(
                    assertion, response, resource, self._assertion_context()
                )
                if warning:
                    self.warnings.append(warning)
        return response, resource

    async def _eval_common(self, common, response, resource):
        """A TestScript.common action group (R5), run in place with its parameters as variables;
        its asserts see the response of the operation before it."""
        key = common.get("keyRef")
        group = next((g for g in self.definition.get("common", []) if g.get("key") == key), None)
        if group is None:
            raise TestScriptError(f"Common actions '{key}' are not found")
        parameters = {
            parameter["name"]: self._resolve(parameter.get("value"))
            for parameter in common.get("parameter", [])
        }
        with self.variables.with_parameters(parameters):
            return await self._eval_actions(group.get("action", []), response, resource)

    async def _execute_operation(self, operation):
        logger.info("%s", operation.get("description"))
        code = operation.get("type", {}).get("code")
        method, suffix = OPERATION_TYPES.get(code, (code or "get", ""))
        method = operation.get("method", method)
        path, _, query = misc.to_s(self._request_target(operation, code, suffix)).partition("?")
        # GET, HEAD and DELETE have no body, whatever sourceId says
        data = None
        if "sourceId" in operation and method.lower() not in ("get", "head", "delete"):
            data = self.source(operation["sourceId"])
        content_type = operation.get("contentType")
        # A Binary sent anywhere but to Binary is its content (e.g. a document to $validate)
        if _is_binary(data) and not path.startswith(("Binary", "/Binary")):
            content_type = data.get("contentType")
            data = base64.b64decode(misc.to_s(data["data"]))

        response, resource = await self.client.execute(
            path,
            method=method,
            data=data,
            params=parse_qs(query),
            headers=self._request_headers(operation),
            accept=operation.get("accept"),
            content_type=content_type,
        )
        self._last = response
        self.last_resource = resource
        if "responseId" in operation:
            self._responses[operation["responseId"]] = response
            self.fixtures[operation["responseId"]] = resource
        return response, resource

    def _request_target(self, operation, code, suffix):
        """The path and query of an operation: its `url`, or the resource type (or the targetId
        fixture's type and id) with `params` and the operation's suffix."""
        if "url" in operation:
            return self._resolve(operation["url"])
        if code == "capabilities":
            return suffix

        target = misc.to_s(operation.get("resource"))
        if "targetId" in operation:
            fixture = self.source(operation["targetId"])
            if not isinstance(fixture, dict):
                raise TestScriptError(f"targetId '{operation['targetId']}' has no resource")
            target = target or fixture["resourceType"]
            target += f"/{fixture['id']}"
            if code == "vread":
                target += f"/_history/{fixture.get('meta', {}).get('versionId')}"

        params = misc.to_s(self._resolve(operation.get("params", "")))
        path, has_query, query = params.partition("?")
        # `params` is a path (`/example`, `$op`), a query (`?name=x`) or a bare query (`profile=x`)
        if "=" in path and not has_query:
            path, query = "", path
        if path.startswith("$") and target:
            path = f"/{path}"
        return f"{target}{path}{suffix}" + (f"?{query}" if query else "")

    def _request_headers(self, operation):
        return {
            header["field"]: self._resolve(header.get("value"))
            for header in operation.get("requestHeader", [])
        }

    def _resolve(self, value):
        return misc.resolve_string_template(value, self.variables)

    def _assertion_context(self):
        return assertation.Context(
            variables=self.variables,
            fixtures=self.fixtures,
            responses=self._responses,
            validator=self._validator(),
            profiles=self.profiles,
        )

    @property
    def profiles(self):
        # TestScript.profile: References with ids (R4), or canonical URLs with the ids in `_profile` (R5)
        if self._profiles is None:
            extensions = self.definition.get("_profile", [])
            self._profiles = [
                (
                    profile
                    if isinstance(profile, dict)
                    else {
                        "id": (
                            (extensions[index] or {}).get("id") if index < len(extensions) else None
                        ),
                        "reference": profile,
                    }
                )
                for index, profile in enumerate(self.definition.get("profile", []))
            ]
        return self._profiles


async def eval(definition, env=None, **options):
    """Runs a TestScript (a dict parsed from JSON/YAML) against the FHIR server described by
    `env` ("baseUrl", "authorization" and values for TestScript variables). Raises on the first
    failed assert and returns the messages of failed warningOnly asserts."""
    return await Evaluator(definition, env, **options).run()
