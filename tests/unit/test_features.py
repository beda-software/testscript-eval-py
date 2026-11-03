import asyncio
import base64
import json

import pytest
from helpers import BASE, assertion, operation, run_script, script

from testscript_eval import Client, Evaluator, FixtureRejected, TestScriptError

PATIENT = {"resourceType": "Patient", "id": "p1", "name": [{"family": "Chalmers"}]}


def body(request):
    return json.loads(request["body"])


class TestOperations:
    def test_maps_operation_types_onto_requests(self, server):
        server.stub("put", "/Patient/p1", status=201, body=PATIENT)
        server.stub("post", "/$validate", query={"profile": "http://x/sd"}, body={})
        server.stub("post", "/$validate-e-rezept", body={})
        server.stub("get", "/metadata", body={})
        server.stub("delete", "/Patient/p1", status=204)

        definition = script(
            fixture=[{"id": "p", "resource": {"reference": "/resources/patient.yaml"}}],
            setup={
                "action": [
                    operation(
                        type={"code": "updateCreate"},
                        resource="Patient",
                        params="/p1",
                        sourceId="p",
                    ),
                    assertion(response="created"),
                    operation(
                        type={"code": "validate"}, params="profile=http://x/sd", sourceId="p"
                    ),
                    assertion(response="okay"),
                    operation(
                        type={"code": "operation"}, params="$validate-e-rezept", sourceId="p"
                    ),
                    assertion(response="okay"),
                    operation(type={"code": "capabilities"}),
                    assertion(response="okay"),
                    operation(method="delete", url="Patient/p1"),
                    assertion(response="noContent"),
                ]
            },
        )

        assert run_script(definition) == []

    def test_sends_request_headers_and_reads_variables_from_a_response_and_its_headers(
        self, server
    ):
        server.stub(
            "post",
            "/Patient",
            status=201,
            body=PATIENT,
            headers={"Location": f"{BASE}/Patient/p1/_history/1"},
            match=lambda r: r["headers"].get("Prefer") == "return=representation",
        )
        server.stub("get", "/Patient/p1/_history/1", body=PATIENT)
        server.stub("get", "/Patient/p1", body=PATIENT)

        definition = script(
            fixture=[{"id": "p", "resource": {"reference": "/resources/patient.yaml"}}],
            variable=[
                {"name": "createdId", "sourceId": "create-response", "expression": "Patient.id"},
                {"name": "location", "sourceId": "create-response", "headerField": "Location"},
                {
                    "name": "family",
                    "sourceId": "create-response",
                    "path": "Patient/name/family/@value",
                },
            ],
            setup={
                "action": [
                    operation(
                        type={"code": "create"},
                        resource="Patient",
                        sourceId="p",
                        responseId="create-response",
                        requestHeader=[{"field": "Prefer", "value": "return=representation"}],
                    )
                ]
            },
            test=[
                {
                    "action": [
                        operation(type={"code": "read"}, url="${location}"),
                        assertion(response="okay"),
                        operation(
                            type={"code": "read"}, resource="Patient", params="/${createdId}"
                        ),
                        assertion(expression="Patient.name.family", value="${family}"),
                        assertion(
                            sourceId="create-response",
                            headerField="Location",
                            operator="contains",
                            value="_history",
                        ),
                    ]
                }
            ],
        )

        assert run_script(definition) == []

    def test_says_what_a_failed_assert_evaluated(self, server):
        outcome = {"resourceType": "OperationOutcome", "issue": [{"severity": "warning"}]}
        server.stub("get", "/OperationOutcome/o1", body=outcome)

        definition = script(
            variable=[{"name": "severity", "defaultValue": "error"}],
            test=[
                {
                    "action": [
                        operation(type={"code": "read"}, resource="OperationOutcome", params="/o1"),
                        assertion(
                            description="Confirm that we have errors.",
                            expression="issue.where(severity='${severity}').count()>0",
                            value="true",
                            warningOnly=True,
                        ),
                        assertion(
                            description="Path",
                            path="$.issue[0].severity",
                            value="error",
                            warningOnly=True,
                        ),
                        assertion(
                            description="Header",
                            headerField="Location",
                            operator="notEmpty",
                            warningOnly=True,
                        ),
                    ]
                }
            ],
        )

        assert run_script(definition) == [
            "Confirm that we have errors.: Expression `issue.where(severity='error').count()>0` "
            'on the response: Got false, expected "true"',
            'Path: Path `$.issue[0].severity` on the response: Got "warning", expected "error"',
            "Header: Response header Location: Got no value, expected a non-empty one",
        ]

    def test_keeps_the_operation_outcome_of_an_error_response_for_asserts(self, server):
        outcome = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid"}],
        }
        server.stub("post", "/Patient", status=422, body=outcome)

        definition = script(
            fixture=[{"id": "p", "resource": {"reference": "/resources/patient.yaml"}}],
            test=[
                {
                    "action": [
                        operation(type={"code": "create"}, resource="Patient", sourceId="p"),
                        assertion(response="unprocessable"),
                        assertion(path="issue[0].code", value="invalid"),
                        assertion(expression="issue.count()", operator="greaterThan", value="0"),
                    ]
                }
            ],
        )

        assert run_script(definition) == []


class TestFormats:
    def test_sends_json_when_an_operation_asks_for_xml(self, server):
        server.stub(
            "put",
            "/Patient/p1",
            body=PATIENT,
            match=lambda r: r["headers"]["Accept"] == "application/fhir+json"
            and r["headers"]["Content-Type"] == "application/fhir+json",
        )

        definition = script(
            fixture=[{"id": "p", "resource": {"reference": "/resources/patient.yaml"}}],
            test=[
                {
                    "action": [
                        operation(
                            type={"code": "update"},
                            resource="Patient",
                            params="/p1",
                            sourceId="p",
                            accept="xml",
                            contentType="xml",
                        ),
                        assertion(contentType="json"),
                        assertion(
                            direction="request",
                            headerField="Accept",
                            operator="contains",
                            value="json",
                        ),
                        # an XPath is evaluated as FHIRPath on the JSON response
                        assertion(
                            expression={
                                "language": "application/xml",
                                "expression": "fhir:Patient/fhir:name/fhir:family/@value",
                            },
                            operator="equals",
                            value="Chalmers",
                        ),
                    ]
                }
            ],
        )

        assert run_script(definition) == []

    def test_sends_a_binary_fixture_as_its_content(self, server, tmp_path):
        document = '{"resourceType":"Bundle","type":"document"}'
        binary = {
            "resourceType": "Binary",
            "contentType": "application/fhir+json",
            "data": base64.b64encode(document.encode()).decode(),
        }
        server.stub(
            "post",
            "/$validate",
            body={"resourceType": "OperationOutcome", "issue": []},
            match=lambda r: r["body"] == document
            and r["headers"]["Content-Type"] == "application/fhir+json",
        )
        (tmp_path / "Fixtures").mkdir()
        (tmp_path / "Fixtures" / "patient.json").write_text(json.dumps(PATIENT))
        (tmp_path / "binary.json").write_text(json.dumps(binary))

        definition = script(
            fixture=[
                {"id": "p", "resource": {"reference": "Fixtures/patient.json"}},
                {"id": "doc", "resource": {"reference": "binary.json"}},
            ],
            variable=[{"name": "family", "sourceId": "p", "expression": "Patient.name.family"}],
            test=[
                {
                    "action": [
                        operation(type={"code": "validate"}, sourceId="doc", contentType="json"),
                        assertion(expression="is(FHIR.OperationOutcome)", value="true"),
                        assertion(sourceId="p", expression="Patient.name.family = '${family}'"),
                    ]
                }
            ],
        )

        assert run_script(definition, root_dir=str(tmp_path)) == []


class TestFixtures:
    def test_autocreates_a_transaction_bundle_and_autodeletes_what_it_created(
        self, server, tmp_path
    ):
        bundle = {
            "resourceType": "Bundle",
            "type": "transaction",
            "entry": [
                {
                    "resource": {k: v for k, v in PATIENT.items() if k != "id"},
                    "request": {"method": "POST", "url": "Patient"},
                }
            ],
        }
        reply = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [{"response": {"status": "201", "location": "Patient/new/_history/1"}}],
        }
        server.stub("post", "/", body=reply)
        server.stub("get", "/Patient/new", body=PATIENT)
        server.stub("delete", "/Patient/new", status=204)
        (tmp_path / "bundle.json").write_text(json.dumps(bundle))

        definition = script(
            fixture=[
                {
                    "id": "b",
                    "autocreate": True,
                    "autodelete": True,
                    "resource": {"reference": "/bundle.json"},
                },
                {"id": "placeholder"},
                {"resource": {"reference": "/bundle.json"}},
            ],
            variable=[
                {
                    "name": "id",
                    "sourceId": "b",
                    "expression": "Bundle.entry.response.location.first()"
                    ".replaceMatches('^Patient/([^/]+).*$', '$1')",
                }
            ],
            test=[
                {
                    "action": [
                        operation(type={"code": "read"}, resource="Patient", params="/${id}"),
                        assertion(response="okay"),
                    ]
                }
            ],
        )

        assert run_script(definition, root_dir=str(tmp_path)) == []
        assert server.made("delete", "/Patient/new")

    def test_autocreates_fixtures_with_ids_in_one_transaction_or_one_by_one(self, server, tmp_path):
        a = {"resourceType": "Patient", "id": "a", "link": [{"other": {"reference": "Patient/b"}}]}
        b = {"resourceType": "Patient", "id": "b", "link": [{"other": {"reference": "Patient/a"}}]}
        reply = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [{"resource": a}, {"resource": b}],
        }

        def is_transaction(request):
            return [e["request"]["url"] for e in body(request)["entry"]] == [
                "Patient/a",
                "Patient/b",
            ]

        server.stub("post", "/", body=reply, match=is_transaction)
        for id in ("a", "b"):
            server.stub("delete", f"/Patient/{id}", status=204)
        (tmp_path / "a.json").write_text(json.dumps(a))
        (tmp_path / "b.json").write_text(json.dumps(b))
        definition = script(
            fixture=[
                {
                    "id": id,
                    "autocreate": True,
                    "autodelete": True,
                    "resource": {"reference": f"{id}.json"},
                }
                for id in ("a", "b")
            ]
        )

        assert run_script(definition, root_dir=str(tmp_path)) == []
        assert len(server.made("post", "/")) == 1
        assert server.made("delete", "/Patient/a")

        server.stub("post", "/", status=405)
        server.stub("put", "/Patient/a", status=201, body=a)
        server.stub("put", "/Patient/b", status=201, body=b)
        assert run_script(definition, root_dir=str(tmp_path)) == []
        assert server.made("put", "/Patient/b")

    def test_fails_not_errors_when_the_server_rejects_a_fixture(self, server):
        server.stub("put", "/Patient/test-patient", status=422)
        definition = script(
            fixture=[
                {
                    "id": "p",
                    "autocreate": True,
                    "resource": {"reference": "/resources/patient.yaml"},
                }
            ]
        )
        with pytest.raises(FixtureRejected, match="failed with status 422"):
            run_script(definition)

    def test_explains_a_server_fixture_that_does_not_exist(self, server):
        server.stub("get", "/Patient/missing", status=404)
        definition = script(fixture=[{"id": "p", "resource": {"reference": "Patient/missing"}}])
        with pytest.raises(TestScriptError, match="Patient/missing could not be read .*status 404"):
            run_script(definition)


class TestScripts:
    def test_runs_common_actions_with_parameters_and_resolves_r5_profile_ids(self, server):
        server.stub("get", "/Patient/p1", body=PATIENT)

        def validator(_resource, profile_url):
            return (
                []
                if profile_url == "http://hl7.org/fhir/StructureDefinition/Patient"
                else ["wrong"]
            )

        definition = script(
            profile=["http://hl7.org/fhir/StructureDefinition/Patient"],
            _profile=[{"id": "patient-profile"}],
            common=[
                {
                    "key": "read-asserts",
                    "parameter": [{"name": "family"}],
                    "action": [
                        assertion(response="okay"),
                        assertion(expression="Patient.name.family", value="${family}"),
                        assertion(validateProfileId="patient-profile"),
                    ],
                }
            ],
            test=[
                {
                    "action": [
                        operation(type={"code": "read"}, resource="Patient", params="/p1"),
                        {
                            "common": {
                                "keyRef": "read-asserts",
                                "parameter": [{"name": "family", "value": "Chalmers"}],
                            }
                        },
                    ]
                }
            ],
        )

        evaluator = Evaluator(definition, {}, client=Client(BASE), validator=validator)
        assert asyncio.run(evaluator.run()) == []
