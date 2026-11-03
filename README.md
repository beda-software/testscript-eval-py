# testscript-eval-py is an engine designed to run TestScript files
## Description
This engine introduces a feature that enables the automatic identification and execution of custom TestScript YAML files. This enhancement is vital as it simplifies the process of verifying FHIR server actions using these scripts. It makes the testing of FHIR server interactions more efficient.
## Install
### Install plugin
```bash
pip install testscript-eval
```
### Setup env
```bash
PYTHONPATH=.
FHIR_SERVER_AUTHORIZATION=
FHIR_SERVER_BASE_URL=
```
## Usage
### General
```bash
pytest
```
### Docker image
```bash
docker run -v "$(pwd)/resources:/app" --env-file ./env/testscript bedasoftware/testscript-eval:latest pytest
```
### Restrictions
1. TestScript files should be stored in the TestScript folder;
2. TestScript files should be in YAML (`.yaml`) or JSON (`.json`) format.

A failed `warningOnly` assert does not fail the test; it is reported as a `TestScriptWarning`.

### As a library
```python
import asyncio

import testscript_eval

definition = testscript_eval.load_file("TestScript/testscript-example.yaml")
warnings = asyncio.run(testscript_eval.eval(definition, {
    "baseUrl": "http://localhost:8080/fhir",
    "authorization": "Basic cm9vdDpzZWNyZXQ=",
}))
```

`testscript_eval.eval` loads fixtures, autocreates them, then runs `setup`, every `test` and
`teardown` (always), and finally autodeletes fixtures. Variables are evaluated where they are used,
so they can read the responses of earlier operations.

- A failed assert raises `testscript_eval.AssertionFailed` (an `AssertionError`). So does a fixture
  the server rejects or does not have (`FixtureRejected`), as that is the server's answer.
- A failed `warningOnly` assert does not stop the script; its message is in the returned list.
- Anything else (an unsupported assert or operator, a missing variable, a `$validate` the server
  could not run) raises `testscript_eval.TestScriptError` or one of its subclasses, `warningOnly` or not.

The `env` dict holds `baseUrl`, `authorization` (sent as is in the `Authorization` header) and
values for TestScript variables. Without one, it is read from `FHIR_SERVER_BASE_URL` and
`FHIR_SERVER_AUTHORIZATION`.

Options:

- `root_dir` (default: the current directory) resolves file fixture references (`.json`, `.yaml`),
  as a `file://` URL or a path from the root: `file://tests/resources/patient.yaml`,
  `/tests/resources/patient.yaml`, `../Fixtures/patient.json`.
- `include_dir` (default: `<root_dir>/tests/resources`) resolves `!include path` tags in YAML fixtures.
- `client`: a `testscript_eval.Client` to send requests with (default: `Client(baseUrl, authorization=...)`).
  `Client(base_url, headers={...}, on_response=callback, session=aiohttp_session)` adds headers to
  every request and passes every `Response` (with its `Request`) to `callback`, e.g. to record requests.
- `validator`: what `validateProfileId` asserts call: any callable (sync or async) taking
  `(resource, profile_url)` and returning the validation error messages (default: `ServerValidator`,
  `$validate` on the server under test).

YAML files are loaded safely, with dates and datetimes kept as strings.

#### Running a script step by step

`eval` is `Evaluator.run`, which is made of three phases that can also be called one at a time,
e.g. to report every test separately:

```python
evaluator = testscript_eval.Evaluator(definition, env)
try:
    await evaluator.start()                     # fixtures, autocreate, setup
    for test in evaluator.tests:
        warnings = await evaluator.run_test(test)  # raises on a failed assert
finally:
    await evaluator.finish()                    # teardown, autodelete; also after a failed start
```

`evaluator.client` and `evaluator.validator` can be swapped between phases.

### Supported features

- Fixtures: contained (`#Type/id`), files (`file://`, `/path`, relative paths; JSON or YAML),
  server references (`Type/id` or a URL), fixtures without a resource (placeholders) or an id.
  `autocreate` puts fixtures with ids in one transaction (so references between them resolve, even in
  cycles; one by one when the server refuses it), posts transaction/batch Bundles to the server root;
  `autodelete` deletes them, including what a transaction Bundle created.
- Operations: every `testscript-operation-codes` type (`read`, `vread`, `search`, `create`, `update`,
  `updateCreate`, `patch`, `delete`, `history`, `transaction`, `batch`, `capabilities`, `validate`,
  `operation` with `params: $name`, `populate`, `extract`, …) or an explicit `method`, with `url`,
  `params` (path, query or `$operation`), `resource`, `targetId`, `sourceId` (a Binary goes as its
  content), `responseId`, `requestHeader`, `accept` and `contentType`
- Variables: `defaultValue`, env values, `expression` (FHIRPath), `path` (JSONPath, or an XPath
  evaluated on the JSON form), `headerField`, against a `sourceId` fixture or response or the last response
- Asserts: `response` (all response codes), `responseCode`, `resource`, `headerField`, `contentType`,
  `path`, `expression`, `value`, `compareToSourceExpression`, `compareToSourcePath`, `minimumId`,
  `navigationLinks`, `requestURL`, `requestMethod`, `validateProfileId`, `sourceId`, and
  `direction: request`; `${variables}` in values, paths and expressions
- Operators: `equals`, `notEquals`, `in`, `notIn`, `contains`, `notContains`, `greaterThan`, `lessThan`,
  `empty`, `notEmpty`, `exists`, `eval`
- R5: `common` actions with parameters, `profile` as canonical URLs with ids in `_profile`
- Not supported: XML (requests and responses are always JSON; `xml` formats are sent as JSON, XML
  fixture files cannot be loaded), `origin`/`destination` (every operation goes to the one server),
  `stopTestOnFail` (a failed assert always ends its test)

## Development
Requires Python 3.11+ and [Poetry](https://python-poetry.org/) 2. Unit tests run offline against a
local stub server:
```bash
poetry install
poetry run pytest tests/unit
```
`make up` runs the TestScripts in `tests/TestScript` against Aidbox in Docker.

## Recommendations
Highly recommend using testscript-eval-py alongside [Kaitenzushi](https://github.com/beda-software/kaitenzushi/) to enhance the TestScript development experience.
## References
1. [Pytest](https://docs.pytest.org/en/7.4.x/)
2. [TestScript](https://hl7.org/fhir/R4/testscript.html)
<p align="center">Made with ❤️ by <a href="https://beda.software">Beda Software</a></p>
