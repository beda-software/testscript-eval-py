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
2. TestScript files should be in YAML format.
## Recommendations
We recommend trying this plugin in pair with [Kaitenzushi](https://github.com/beda-software/kaitenzushi/).
## Refences
1. [Pytest](https://docs.pytest.org/en/7.4.x/)
2. [TestScript](https://hl7.org/fhir/R4/testscript.html)
<p align="center">Made with ❤️ by <a href="https://beda.software">Beda Software</a></p>
