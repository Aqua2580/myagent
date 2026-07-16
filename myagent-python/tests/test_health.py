from fastapi.testclient import TestClient

from myagent.config import Settings
from myagent.main import create_app


def create_test_client() -> TestClient:
    settings = Settings(environment="test", _env_file=None)
    return TestClient(create_app(settings))


def test_liveness() -> None:
    response = create_test_client().get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "myagent-python",
        "version": "0.1.0",
    }


def test_readiness() -> None:
    response = create_test_client().get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"application": "ok"},
    }


def test_openapi_is_available_outside_production() -> None:
    response = create_test_client().get("/openapi.json")

    assert response.status_code == 200

