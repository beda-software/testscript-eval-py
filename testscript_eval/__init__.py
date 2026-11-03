from importlib.metadata import PackageNotFoundError, version

from .client import Client, Request, Response
from .errors import (
    AssertionFailed,
    FixtureRejected,
    NotImplementedAssert,
    NotImplementedOperation,
    TestScriptError,
    TestScriptWarning,
)
from .eval import Evaluator, eval
from .misc import load_file
from .server_validator import ServerValidator

__all__ = [
    "AssertionFailed",
    "Client",
    "Evaluator",
    "FixtureRejected",
    "NotImplementedAssert",
    "NotImplementedOperation",
    "Request",
    "Response",
    "ServerValidator",
    "TestScriptError",
    "TestScriptWarning",
    "eval",
    "load_file",
]

__title__ = "testscript_eval"
try:
    __version__ = version("testscript_eval")
except PackageNotFoundError:  # run from a source checkout that is not installed
    __version__ = "0.0.0+unknown"
__author__ = "beda.software"
__license__ = "MIT License"
__copyright__ = "Copyright 2023 beda.software"

# Version synonym
VERSION = __version__
