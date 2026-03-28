"""Production HTTP error shaping (no internal leakage in JSON)."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException, Request

from src.error_handling import http_exception_handler


@pytest.fixture
def mock_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/test",
        "headers": [],
    }
    return Request(scope)


def test_production_500_hides_detail(mock_request: Request) -> None:
    exc = HTTPException(status_code=500, detail="secret_postgres_connection_string_xyz")
    with patch("src.error_handling.settings") as s:
        s.is_production = True
        resp = http_exception_handler(mock_request, exc)
    assert resp.status_code == 500
    body = resp.body.decode()
    assert "secret_postgres" not in body
    assert "error_id" in body
    assert "An error occurred" in body or "try again" in body


def test_development_500_passes_detail(mock_request: Request) -> None:
    exc = HTTPException(status_code=500, detail="debug_visible_message")
    with patch("src.error_handling.settings") as s:
        s.is_production = False
        resp = http_exception_handler(mock_request, exc)
    assert resp.status_code == 500
    assert "debug_visible_message" in resp.body.decode()


def test_production_4xx_passes_safe_detail(mock_request: Request) -> None:
    exc = HTTPException(status_code=400, detail="Invalid webhook signature")
    with patch("src.error_handling.settings") as s:
        s.is_production = True
        resp = http_exception_handler(mock_request, exc)
    assert resp.status_code == 400
    assert "Invalid webhook signature" in resp.body.decode()
