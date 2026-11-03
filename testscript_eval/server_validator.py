import json

from .errors import TestScriptError


class ServerValidator:
    """The default validator for validateProfileId asserts: runs $validate on the FHIR server
    under test. A validator is any callable (sync or async) taking `(resource, profile_url)` and
    returning the validation errors, raising TestScriptError when no validation happened."""

    def __init__(self, client):
        self.client = client

    async def __call__(self, resource, profile_url):
        # Pass the profile both ways: as the $validate `profile` parameter, and in meta.profile,
        # which servers that ignore the parameter (e.g. Aidbox) validate against
        meta = resource.get("meta", {})
        payload = {
            **resource,
            "meta": {
                **meta,
                "profile": list(dict.fromkeys([*meta.get("profile", []), profile_url])),
            },
        }
        response, outcome = await self.client.execute(
            f"{resource['resourceType']}/$validate",
            method="post",
            data=payload,
            params={"profile": profile_url},
        )
        # No validation happened (auth, $validate unsupported, server error): an engine/
        # infrastructure error, never a check failure, so warningOnly does not hide it
        if response.status in (401, 403, 404, 405) or response.status >= 500:
            raise TestScriptError(
                f"$validate against {profile_url} could not run: status {response.status}: {outcome}"
            )
        if not isinstance(outcome, dict):
            # Non-2xx: the body comes back wrapped in an ErrorBody
            try:
                outcome = json.loads(str(outcome))
            except ValueError:
                outcome = None
        if not isinstance(outcome, dict) or outcome.get("resourceType") != "OperationOutcome":
            raise TestScriptError(
                f"$validate against {profile_url} returned no OperationOutcome "
                f"(status {response.status}): {outcome}"
            )
        errors = [
            f"[{issue.get('severity')}] {', '.join(issue.get('expression', []))}: "
            f"{issue.get('diagnostics') or issue.get('details', {}).get('text', '')}"
            for issue in outcome.get("issue", [])
            if issue.get("severity") in ("error", "fatal")
        ]
        # A 2xx, or a 4xx such as 400/422 with an OperationOutcome, is the validation result
        if response.status >= 400 and not errors:
            errors.append(f"status {response.status}")
        return errors
