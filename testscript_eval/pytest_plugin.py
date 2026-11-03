import asyncio
import os
import warnings

import pytest

import testscript_eval
from testscript_eval.errors import TestScriptWarning
from testscript_eval.misc import load_file


def pytest_collect_file(parent, file_path):
    if file_path.suffix in (".yaml", ".json") and file_path.parent.name == "TestScript":
        return TestScriptFile.from_parent(parent, path=file_path)


class TestScriptFile(pytest.File):
    def collect(self):
        include_dir = os.path.join(os.getcwd(), "tests", "resources")
        raw = load_file(str(self.path), include_dir=include_dir)
        yield TestScriptItem.from_parent(self, name=raw["name"], spec=raw)


def env():
    return {
        "baseUrl": os.environ.get("FHIR_SERVER_BASE_URL"),
        "authorization": os.environ.get("FHIR_SERVER_AUTHORIZATION"),
    }


class TestScriptItem(pytest.Item):
    def __init__(self, *, spec, **kwargs):
        super().__init__(**kwargs)
        self.spec = spec

    def runtest(self):
        for message in asyncio.run(testscript_eval.eval(self.spec, env())):
            warnings.warn(TestScriptWarning(message))


def pytest_addoption(parser, pluginmanager):
    parser.addoption(
        "--testscript-env-file",
        help="Config file to use, defaults to %(default)s",
        default=None,
    )
