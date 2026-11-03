class TestScriptError(Exception):
    """An engine, script or infrastructure error: always fails the script, warningOnly or not."""

    __test__ = False


class AssertionFailed(TestScriptError, AssertionError):
    """A failed check of an assert. It is the only error a warningOnly assert turns into a
    warning; anything else (engine, script or infrastructure errors) always fails the script."""


class FixtureRejected(AssertionFailed):
    """The server did not accept a fixture (autocreate), or does not have one the script reads
    from it: the server's answer, so a failed check, not an engine error."""


class NotImplementedOperation(TestScriptError):
    pass


class NotImplementedAssert(TestScriptError):
    pass


class TestScriptWarning(UserWarning):
    """A failed warningOnly assert: reported, but does not fail the test script."""

    __test__ = False
