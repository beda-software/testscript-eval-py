import asyncio
import os

import pytest
import yaml
from pytest_asyncio.plugin import pytest_runtest_setup

import testscript_eval


def pytest_collect_file(parent, file_path):
    if file_path.suffix == ".yaml" and file_path.parent.name == "TestScript":
        return TestScriptFile.from_parent(parent, path=file_path)


class TestScriptFile(pytest.File):
    def collect(self):
        raw = yaml.safe_load(self.path.open())
        yield TestScriptItem.from_parent(self, name=raw["name"], spec=raw)


env = {
    "baseUrl": os.environ.get("FHIR_SERVER_BASE_URL"),
    "authorization": os.environ.get("FHIR_SERVER_AUTHORIZATION"),
}


class TestScriptItem(pytest.Item):
    def __init__(self, *, spec, **kwargs):
        super().__init__(**kwargs)
        self.spec = spec

    def runtest(self):
        loop = asyncio.get_event_loop_policy().new_event_loop()
        loop.run_until_complete(testscript_eval.eval(self.spec, env))
        loop.close()


def pytest_addoption(parser, pluginmanager):
    parser.addoption(
        "--testscript-env-file",
        help="Config file to use, defaults to %(default)s",
        default=None,
    )
