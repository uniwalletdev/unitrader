"""Production-safe HTTP error responses and third-party logging levels."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from config import settings

logger = logging.getLogger(__name__)


def configure_third_party_loggers() -> None:
    """Reduce outbound HTTP noise from httpx/Twilio in non-debug runs."""
    if settings.debug:
        return
    for name in ("httpx", "httpcore", "twilio.http_client", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _detail_payload(detail: Any) -> dict[str, Any]:
    """Match FastAPI's default JSON shape for HTTPException."""
    return {"detail": detail}


def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Hide internal 5xx details in production; always log server-side."""
    if settings.is_production and exc.status_code >= 500:
        error_id = str(uuid.uuid4())
        logger.error(
            "HTTPException %s %s error_id=%s detail=%r",
            exc.status_code,
            request.url.path,
            error_id,
            exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": "An error occurred. Please try again later.",
                "error_id": error_id,
            },
        )
    return JSONResponse(status_code=exc.status_code, content=_detail_payload(exc.detail))
