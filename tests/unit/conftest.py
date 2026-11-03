import pytest
from helpers import BASE, SERVER


@pytest.fixture
def server():
    SERVER.reset()
    yield SERVER
    # A request no stub answered is a test failure, whatever the script made of the 599
    assert not SERVER.errors, SERVER.errors


@pytest.fixture
def env():
    return {"baseUrl": BASE, "authorization": "Basic dGVzdDp0ZXN0"}
