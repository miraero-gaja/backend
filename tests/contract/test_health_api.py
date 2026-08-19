"""Contract checks for the process-liveness endpoint."""

from fastapi.testclient import TestClient


def test_healthz_reports_process_liveness(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

