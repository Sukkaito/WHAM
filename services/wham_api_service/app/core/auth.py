from __future__ import annotations

import logging

from fastapi import HTTPException, status
from fastapi.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.logging import log_event
from app.core.token_registry import verify_api_key
from app.models.schemas import AuthPayload

from app.core.settings import settings

AUTH_SUBJECT_HEADER = settings.auth_subject_header
AUTH_API_KEY_HEADER = settings.auth_api_key_header

_EXEMPT_PATHS = {
    "/docs",
    "/openapi.json",
    "/redoc",
    "/",
}


def get_request_auth(request: Request) -> AuthPayload:
    auth = getattr(request.state, "auth_payload", None)
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication context.",
        )
    return auth


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS" or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        subject = request.headers.get(AUTH_SUBJECT_HEADER, "").strip()
        api_key = request.headers.get(AUTH_API_KEY_HEADER, "").strip()
        logger = logging.getLogger(__name__)

        if not subject or not api_key:
            log_event(
                logger,
                "auth_missing",
                method=request.method,
                path=request.url.path,
            )
            return JSONResponse(
                content={"detail": "Missing authentication headers."},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        if not verify_api_key(subject=subject, api_key=api_key):
            log_event(
                logger,
                "auth_invalid",
                method=request.method,
                path=request.url.path,
                subject=subject,
            )
            return JSONResponse(
                content={"detail": "Invalid API key."},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        request.state.auth_payload = AuthPayload(subject=subject, api_key=api_key)
        log_event(
            logger,
            "auth_ok",
            method=request.method,
            path=request.url.path,
            subject=subject,
        )
        return await call_next(request)