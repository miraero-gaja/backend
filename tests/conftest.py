"""Shared fixtures for API-level tests."""

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator["TestClient"]:
    """Run each test against the application, including its lifespan hooks."""

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
