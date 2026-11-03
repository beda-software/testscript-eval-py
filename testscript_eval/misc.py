import json
import os
import re
from collections import abc

import yaml
from fhirpathpy import evaluate as fhirpath_evaluate
from fhirpathpy.engine import nodes
from fhirpathpy.models import models
from jsonpath_ng.ext import parse as jsonpath_parse

from .errors import TestScriptError

# fhirpathpy types a plain resource dict, such as the root of an expression, as a System type,
# so `is(FHIR.OperationOutcome)` or `ofType(Patient)` on the root are false. A dict with a
# resourceType is that FHIR resource type
_from_value = nodes.TypeInfo.from_value


def _resource_type_info(value):
    if isinstance(value, abc.Mapping) and isinstance(value.get("resourceType"), str):
        return nodes.TypeInfo(name=value["resourceType"], namespace=nodes.TypeInfo.FHIR)
    return _from_value(value)


nodes.TypeInfo.from_value = staticmethod(_resource_type_info)


def to_s(value):
    """A value as the string TestScript compares it as ("true", "200")."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def show(value):
    """A value for a failure message: "Peter", false, ["Bundle"], null."""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(value)


def fhirpath(resource, expression, context=None):
    # The FHIR R4 model lets FHIRPath resolve choice elements (e.g. `value` for
    # valueCodeableConcept) and types (ofType, is, as) on plain JSON resources.
    # %rootResource is the resource itself, as TestScript resources are not contained
    return fhirpath_evaluate(
        resource, expression, {"rootResource": resource, **(context or {})}, models["r4"]
    )


def expression_of(expression):
    """A TestScript expression: a FHIRPath string, or an Expression ({"expression": ...})."""
    return expression.get("expression") if isinstance(expression, dict) else expression


def evaluate(resource, expression, context=None):
    """Evaluates a TestScript expression: FHIRPath, or for an Expression in `application/xml`
    an XPath (`fhir:Patient/fhir:name/fhir:family/@value`), evaluated as FHIRPath on the JSON form.
    """
    if isinstance(expression, dict) and "xml" in to_s(expression.get("language")):
        if not isinstance(resource, dict):
            return []
        return fhirpath(
            resource, xpath_to_fhirpath(expression["expression"], resource.get("resourceType"))
        )
    return fhirpath(resource, expression_of(expression), context)


def path(resource, path):
    """A TestScript `path`: JSONPath (`$.issue[0].code`, also without the `$.`), or an XPath of
    the XML form (`Bundle/entry/resource/Patient/id`), evaluated as FHIRPath on the JSON form."""
    if not isinstance(resource, dict):
        return []
    if is_xpath(path):
        return fhirpath(resource, xpath_to_fhirpath(path, resource.get("resourceType")))
    return [match.value for match in jsonpath_parse(path).find(resource)]


def is_xpath(path):
    return not path.startswith("$") and "/" in path


def xpath_to_fhirpath(path, resource_type):
    # Steps are elements; a capitalized step is the resource in a `resource` element (ofType),
    # an `@value` step is the value itself; namespace prefixes and predicates are dropped
    steps = [
        re.sub(r"\[.*\]$", "", re.sub(r"^\w+:", "", step)) for step in path.lstrip("/").split("/")
    ]
    if steps and steps[0] == resource_type:
        steps.pop(0)
    expression = []
    for step in steps:
        if not step or step.startswith("@"):
            continue
        expression.append(f"ofType({step})" if step[0].isupper() and expression else step)
    return ".".join(expression)


def resolve_string_template(value, env):
    if not isinstance(value, str):
        return value
    return re.sub(r"\$\{([\S\s]+?)\}", lambda match: to_s(env[match.group(1)]), value)


class _YamlLoader(yaml.SafeLoader):
    include_dir = "."


# Dates and datetimes stay strings: FHIR primitives, not Python date/datetime objects
_YamlLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _include(loader, node):
    path = os.path.join(loader.include_dir, loader.construct_scalar(node))
    return load_file(path, include_dir=loader.include_dir)


_YamlLoader.add_constructor("!include", _include)


def load_yaml(content, include_dir="."):
    """Loads YAML safely; `!include path` embeds another file resolved against `include_dir`."""
    loader_class = type("YamlLoader", (_YamlLoader,), {"include_dir": include_dir})
    return yaml.load(content, Loader=loader_class)


def load_file(path, include_dir=None):
    """Loads a TestScript or a fixture from a .json or .yaml file."""
    if include_dir is None:
        include_dir = os.path.dirname(path)
    if not os.path.exists(path):
        raise TestScriptError(f"File {path} is not found")
    with open(path) as f:
        content = f.read()
    # JSON files are parsed as JSON: valid JSON is not always valid YAML, e.g. with tab indentation
    if path.lower().endswith(".json"):
        return json.loads(content)
    return load_yaml(content, include_dir=include_dir)
