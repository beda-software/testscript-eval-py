import asyncio
import json
import os
import re

import pytest
from helpers import BASE, FIXTURES_DIR, assertion, operation, run_script, script

import testscript_eval
from testscript_eval import AssertionFailed, Client, Evaluator, TestScriptError, misc

PATIENT = {
    "resourceType": "Patient",
    "id": "example",
    "name": [{"use": "official", "given": ["Peter", "James"], "family": "Chalmers"}],
}
OK_OUTCOME = {"resourceType": "OperationOutcome", "issue": []}
PROFILE = "http://hl7.org/fhir/StructureDefinition/Patient"


def read_patient(*asserts):
    return [
        operation(type={"code": "read"}, resource="Patient", params="/example"),
        *[assertion(**a) for a in asserts],
    ]


def body(request):
    return json.loads(request["body"])


class TestHL7Example:
    @pytest.fixture
    def definition(self):
        return misc.load_file(os.path.join(FIXTURES_DIR, "scripts", "testscript-example.yaml"))

    @pytest.fixture(autouse=True)
    def stubs(self, server):
        server.stub("delete", "/Patient/example", status=204)
        server.stub(
            "put",
            "/Patient/example",
            status=201,
            body=PATIENT,
            match=lambda r: body(r)["resourceType"] == "Patient" and body(r)["id"] == "example",
        )
        server.stub(
            "get",
            "/Patient/example",
            body=PATIENT,
            headers={"Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        )
        server.stub("post", "/Patient/$validate", query={"profile": PROFILE}, body=OK_OUTCOME)

    def test_passes_and_runs_setup_tests_and_teardown(self, server, definition):
        assert run_script(definition) == []
        assert len(server.made("delete", "/Patient/example")) == 2
        reads = server.made(
            "get",
            "/Patient/example",
            match=lambda r: r["headers"].get("Authorization") == "Basic dGVzdDp0ZXN0",
        )
        assert len(reads) == 2
        (validate,) = server.made("post", "/Patient/$validate", query={"profile": PROFILE})
        assert body(validate)["meta"] == {"profile": [PROFILE]}

    def test_fails_on_another_family_name_and_still_tears_down(self, server, definition):
        server.stub(
            "get",
            "/Patient/example",
            body={**PATIENT, "name": [{"family": "Smith", "given": ["Peter"]}]},
        )
        with pytest.raises(AssertionFailed, match="Smith"):
            run_script(definition)
        assert len(server.made("delete", "/Patient/example")) == 2

    def test_reports_a_failed_warning_only_assert_as_a_warning(self, server, definition):
        server.stub("get", "/Patient/example", body=PATIENT)
        (warning,) = run_script(definition)
        assert re.search(r"Last-Modified is present.*Got no value", warning, re.S)

    def test_fails_on_validation_errors(self, server, definition):
        outcome = {
            **OK_OUTCOME,
            "issue": [
                {"severity": "error", "expression": ["Patient.gender"], "diagnostics": "bad gender"}
            ],
        }
        server.stub("post", re.compile(r"/Patient/\$validate"), status=422, body=outcome)
        with pytest.raises(AssertionFailed, match=r"\[error\] Patient.gender: bad gender"):
            run_script(definition)

    def test_raises_an_engine_error_when_validate_cannot_run(self, server, definition):
        server.stub("post", re.compile(r"/Patient/\$validate"), status=404)
        with pytest.raises(TestScriptError, match="could not run: status 404") as error:
            run_script(definition)
        assert not isinstance(error.value, AssertionFailed)


def read_fixture(fixture="p"):
    return [
        operation(type={"code": "read"}, resource="Patient", targetId=fixture),
        assertion(response="okay"),
    ]


class TestFixtures:
    def test_autocreates_uses_the_server_assigned_id_and_autodeletes(self, server):
        server.stub(
            "post",
            "/Patient",
            status=201,
            headers={"Location": f"{BASE}/Patient/new-id/_history/1"},
        )
        server.stub("get", "/Patient/new-id", body=PATIENT)
        server.stub("delete", "/Patient/new-id", status=204)

        definition = script(
            fixture=[
                {
                    "id": "p",
                    "autocreate": True,
                    "autodelete": True,
                    "resource": {"reference": "file://resources/patient-no-id.yaml"},
                }
            ],
            test=[{"name": "read", "action": read_fixture()}],
        )

        assert run_script(definition) == []
        assert server.made("get", "/Patient/new-id")
        assert server.made("delete", "/Patient/new-id")

    def test_creates_fixtures_from_files_under_their_id(self, server):
        server.stub("put", "/Patient/test-patient", status=201)
        server.stub("delete", "/Patient/test-patient", status=204)
        server.stub(
            "get",
            "/Patient?name=Chalmers&_count=1",
            body={"resourceType": "Bundle", "link": []},
        )

        definition = script(
            fixture=[
                {
                    "id": "p",
                    "autocreate": True,
                    "autodelete": True,
                    "resource": {"reference": "file://resources/patient.yaml"},
                }
            ],
            variable=[{"name": "family", "sourceId": "p", "expression": "Patient.name.family"}],
            test=[
                {
                    "name": "search",
                    "action": [
                        operation(
                            type={"code": "search"},
                            resource="Patient",
                            params="?name=${family}&_count=1&empty=",
                        ),
                        assertion(resource="Bundle", navigationLinks=True),
                        # a path matching one value is compared as that value
                        assertion(
                            path="$.resourceType",
                            operator="equals",
                            value="Bundle",
                            warningOnly=True,
                        ),
                    ],
                }
            ],
        )

        assert run_script(definition) == []
        assert server.made("delete", "/Patient/test-patient")

    def test_loads_fixtures_from_paths_relative_to_the_root_directory(self, server):
        server.stub("get", "/Patient/test-patient", body=PATIENT)
        definition = script(
            fixture=[{"id": "p", "resource": {"reference": "/resources/patient.yaml"}}],
            test=[{"name": "read", "action": read_fixture()}],
        )
        assert run_script(definition) == []

    def test_parses_json_fixture_files_as_json(self, server, tmp_path):
        server.stub("get", "/Patient/tabbed", body=PATIENT)
        (tmp_path / "patient.json").write_text(
            '{\n\t"resourceType": "Patient",\n\t"id": "tabbed"\n}\n'
        )
        definition = script(
            fixture=[{"id": "p", "resource": {"reference": "/patient.json"}}],
            test=[{"name": "read", "action": read_fixture()}],
        )
        assert run_script(definition, root_dir=str(tmp_path)) == []

    def test_autodeletes_created_fixtures_when_a_later_autocreate_fails(self, server):
        server.stub("put", "/Patient/test-patient", status=201, body=PATIENT)
        server.stub("post", "/Patient", status=500, body="boom")
        server.stub("delete", "/Patient/example", status=204)

        definition = script(
            fixture=[
                {
                    "id": "a",
                    "autocreate": True,
                    "autodelete": True,
                    "resource": {"reference": "file://resources/patient.yaml"},
                },
                {
                    "id": "b",
                    "autocreate": True,
                    "autodelete": True,
                    "resource": {"reference": "file://resources/patient-no-id.yaml"},
                },
            ]
        )

        with pytest.raises(TestScriptError, match="'b' failed with status 500: boom"):
            run_script(definition)
        # `a` was created as test-patient, the server answered with the `example` body
        assert server.made("delete", "/Patient/example")


class TestPhases:
    @pytest.fixture
    def definition(self):
        return script(
            fixture=[
                {
                    "id": "p",
                    "autocreate": True,
                    "autodelete": True,
                    "resource": {"reference": "file://resources/patient.yaml"},
                }
            ],
            variable=[{"name": "family", "sourceId": "p", "expression": "Patient.name.family"}],
            test=[
                {"name": "pass", "action": read_patient({"response": "okay"})},
                {
                    "name": "warn",
                    "action": read_patient(
                        {
                            "expression": "Patient.name.given.first()",
                            "value": "${family}",
                            "warningOnly": True,
                        }
                    ),
                },
                {
                    "name": "fail",
                    "action": read_patient(
                        {"expression": "Patient.name.family = 'Smith'", "warningOnly": False}
                    ),
                },
            ],
        )

    @pytest.fixture
    def evaluator(self, definition, env):
        return Evaluator(definition, env, root_dir=FIXTURES_DIR)

    @pytest.fixture(autouse=True)
    def stubs(self, server):
        server.stub("put", "/Patient/test-patient", status=201)
        server.stub("delete", "/Patient/test-patient", status=204)
        server.stub("get", "/Patient/example", body=PATIENT)

    def test_runs_tests_one_at_a_time_and_returns_each_tests_warnings(self, server, evaluator):
        async def scenario():
            await evaluator.start()
            passing, warning, failing = evaluator.tests
            assert await evaluator.run_test(passing) == []
            (message,) = await evaluator.run_test(warning)
            assert 'Got "Peter"' in message
            with pytest.raises(AssertionFailed):
                await evaluator.run_test(failing)
            assert not server.made("delete", "/Patient/test-patient")

            await evaluator.finish()
            await evaluator.finish()

        asyncio.run(scenario())
        assert len(server.made("delete", "/Patient/test-patient")) == 1

    def test_cleans_up_after_a_failed_start(self, server, definition, evaluator):
        server.stub(
            "put",
            "/Patient/test-patient",
            status=201,
            body={"resourceType": "Patient", "id": "test-patient"},
        )
        definition["variable"] = [
            {"name": "missing", "sourceId": "p", "expression": "Patient.gender"}
        ]
        definition["setup"] = {
            "action": [operation(type={"code": "read"}, resource="Patient", params="/${missing}")]
        }

        async def scenario():
            with pytest.raises(AssertionFailed, match="Variable missing: no value in p"):
                await evaluator.start()
            await evaluator.finish()

        asyncio.run(scenario())
        assert server.made("delete", "/Patient/test-patient")

    def test_sends_requests_through_a_given_client_passing_every_response_on(
        self, server, evaluator
    ):
        responses = []
        evaluator.client = Client(
            BASE, headers={"Authorization": "Bearer token"}, on_response=responses.append
        )

        async def scenario():
            await evaluator.start()
            await evaluator.run_test(evaluator.tests[0])
            await evaluator.finish()

        asyncio.run(scenario())
        assert [(r.request.method, r.status) for r in responses] == [
            ("put", 201),
            ("get", 200),
            ("delete", 204),
        ]
        assert server.made(
            "get",
            "/Patient/example",
            match=lambda r: r["headers"].get("Authorization") == "Bearer token",
        )

    def test_validates_with_a_given_validator(self, server, evaluator):
        evaluator.validator = lambda resource, profile_url: [
            f"{resource['resourceType']} does not conform to {profile_url}"
        ]

        async def scenario():
            await evaluator.start()
            test = {"action": read_patient({"validateProfileId": "http://example.org/profile"})}
            with pytest.raises(
                AssertionFailed, match="Patient does not conform to http://example.org/profile"
            ):
                await evaluator.run_test(test)

        asyncio.run(scenario())
        assert not server.made("post", re.compile(r"\$validate"))


class TestAsserts:
    @pytest.fixture(autouse=True)
    def stubs(self, server):
        server.stub("get", "/Patient/example", body=PATIENT)

    def test_evaluates_boolean_expressions_with_variables_from_env(self):
        definition = script(
            variable=[{"name": "family", "defaultValue": "Chalmers"}],
            setup={
                "action": read_patient(
                    {"expression": "Patient.name.family = 'Chalmers'"},
                    {
                        "expression": "Patient.name.given.first()",
                        "value": "${family}",
                        "warningOnly": True,
                    },
                    {"responseCode": "200,201", "operator": "in"},
                    {"contentType": "application/fhir+json"},
                )
            },
        )
        (warning,) = run_script(definition)
        assert 'Got "Peter", expected "Chalmers"' in warning

    def test_checks_the_request_with_direction_request(self):
        definition = script(
            setup={
                "action": read_patient(
                    {
                        "direction": "request",
                        "requestURL": "Patient/example",
                        "operator": "contains",
                    },
                    {"direction": "request", "requestMethod": "GET"},
                    {
                        "direction": "request",
                        "headerField": "Accept",
                        "operator": "contains",
                        "value": "json",
                    },
                    {"direction": "request", "requestMethod": "post", "warningOnly": True},
                )
            }
        )
        (warning,) = run_script(definition)
        assert 'Got "get", expected "post"' in warning

    def test_requires_an_operation_before_an_assert(self):
        definition = script(test=[{"action": [{"assert": {"response": "okay"}}]}])
        with pytest.raises(TestScriptError, match="no preceding operation"):
            run_script(definition)

    def test_requires_variables_without_a_default_value_where_they_are_used(self):
        definition = script(variable=[{"name": "missing", "hint": "[id]"}])
        assert run_script(definition) == []

        definition["setup"] = {"action": [operation(resource="Patient", params="/${missing}")]}
        with pytest.raises(TestScriptError, match=r"Missing missing variable \(\[id\]\)"):
            run_script(definition)

    def test_treats_a_404_body_as_no_resource(self, server):
        server.stub("get", "/Patient/example", status=404, body="gone")
        definition = script(
            setup={"action": read_patient({"response": "notFound"}, {"resource": "Patient"})}
        )
        with pytest.raises(AssertionFailed, match="No resource in the response"):
            run_script(definition)


def test_reads_the_server_from_the_environment(server, monkeypatch):
    monkeypatch.setenv("FHIR_SERVER_BASE_URL", BASE)
    server.stub("get", "/Patient/example", body=PATIENT)
    definition = script(setup={"action": read_patient({"response": "okay"})})
    assert asyncio.run(testscript_eval.eval(definition)) == []
