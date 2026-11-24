import pytest
from fastapi import HTTPException
from starlette.requests import Request
from fastapi.testclient import TestClient

from main import app, get_local_access_context


def _request(host: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/profile",
        "headers": [],
        "client": (host, 12345),
        "server": ("localhost", 8000),
        "scheme": "http",
    })


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_local_access_context_accepts_loopback_clients(host: str) -> None:
    context = get_local_access_context(_request(host))

    assert context.subject.subject_id == "local-api"
    assert context.scope.owner_id == "local-user"


@pytest.mark.parametrize("host", ["192.168.1.20", "10.0.0.5", "203.0.113.10"])
def test_local_access_context_rejects_non_loopback_clients(host: str) -> None:
    with pytest.raises(HTTPException) as error:
        get_local_access_context(_request(host))

    assert error.value.status_code == 403



def test_protected_api_routes_reject_non_loopback_test_clients() -> None:
    with TestClient(app) as client:
        assert client.get("/api/settings").status_code == 403
        assert client.get("/api/providers").status_code == 403
        assert client.get("/api/runtime/ollama/status").status_code == 403
