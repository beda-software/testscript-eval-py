from contextlib import contextmanager

from . import misc
from .errors import AssertionFailed, TestScriptError

SOURCE_KEYS = ("expression", "path", "headerField")


def _blank(value):
    return value is None or misc.to_s(value) == ""


def _first(result):
    return result[0] if isinstance(result, list) and result else None


class Variables:
    """TestScript variables, evaluated each time they are used: a variable may read the response
    of an operation that ran after the script started (e.g. `sourceId` = a setup responseId).

    A variable's value is, in order: the env value of its name, an `expression` (FHIRPath),
    `path` (JSONPath or XPath) or `headerField` against its `sourceId` (a fixture or response;
    the last response without one), or its `defaultValue`.
    """

    def __init__(self, definitions, env, evaluator):
        self.definitions = {variable["name"]: variable for variable in definitions}
        self.env = env
        self.evaluator = evaluator
        self.parameters = None

    @contextmanager
    def with_parameters(self, parameters):
        """Common action parameters, as variables while the action runs."""
        previous = self.parameters
        self.parameters = {**(previous or {}), **parameters}
        try:
            yield
        finally:
            self.parameters = previous

    def __contains__(self, name):
        return name in self.definitions or name in self.env

    def __getitem__(self, name):
        return self.fetch(name)

    def fetch(self, name):
        if self.parameters and name in self.parameters:
            return self.parameters[name]
        if not _blank(self.env.get(name)):
            return self.env[name]

        variable = self.definitions.get(name)
        if variable is None:
            raise TestScriptError(f"Unknown variable {name}")
        value = self._evaluate(variable)
        if _blank(value):
            value = variable.get("defaultValue")
        if not _blank(value):
            return value

        # read from a response or fixture that does not have it: the server's answer, a failed check
        if any(key in variable for key in SOURCE_KEYS):
            raise AssertionFailed(
                f"Variable {name}: no value in {variable.get('sourceId', 'the last response')}"
            )
        hint = f" ({variable['hint']})" if variable.get("hint") else ""
        raise TestScriptError(f"Missing {name} variable{hint}")

    def _evaluate(self, variable):
        if "headerField" in variable:
            response = self.evaluator.response_of(variable.get("sourceId"))
            return response.headers.get(variable["headerField"]) if response else None
        if "expression" in variable:
            return _first(misc.evaluate(self._source(variable), variable["expression"]))
        if "path" in variable:
            return _first(misc.path(self._source(variable), variable["path"]))
        return None

    def _source(self, variable):
        if "sourceId" in variable:
            return self.evaluator.source(variable["sourceId"])
        return self.evaluator.last_resource if self.evaluator.response_of() else None
