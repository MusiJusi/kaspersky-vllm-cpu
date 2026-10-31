"""Pure ASGI middleware: metadata-only audit logs, including streaming requests."""

import logging
import time
import uuid

from app.safe_logging import METHODS, ROUTES

logger = logging.getLogger("app.audit")


class RequestAuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        status = 500

        async def audited_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", request_id.encode("ascii"))
                ]
            await send(message)

        try:
            await self.app(scope, receive, audited_send)
        finally:
            logger.info(
                "http_request",
                extra={
                    "event": "http_request",
                    "request_id": request_id,
                    "method": scope["method"] if scope["method"] in METHODS else "other",
                    "route": scope["path"] if scope["path"] in ROUTES else "other",
                    "status": status,
                    "duration_ms": (time.perf_counter() - started) * 1000,
                },
            )
