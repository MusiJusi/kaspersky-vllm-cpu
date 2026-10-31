"""Require Bearer authentication on every route except health/metrics probes."""

import hashlib
import os
import secrets


class BearerAuthMiddleware:
    def __init__(self, app):
        self.app = app
        token = os.environ.get("VLLM_API_KEY", "")
        if len(token) < 32:
            raise ValueError("A valid API token is required.")
        self.token_hash = hashlib.sha256(token.encode()).digest()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        if scope["type"] == "http" and (
            scope.get("method") == "OPTIONS"
            or (scope.get("method") in {"GET", "HEAD"} and scope["path"] in {"/health", "/metrics"})
        ):
            return await self.app(scope, receive, send)
        values = [value for name, value in scope.get("headers", []) if name.lower() == b"authorization"]
        allowed = False
        if len(values) == 1:
            scheme, separator, token = values[0].partition(b" ")
            if separator and scheme.lower() == b"bearer":
                allowed = secrets.compare_digest(hashlib.sha256(token).digest(), self.token_hash)
        if allowed:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4401})
        body = b'{"error":"Unauthorized"}'
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", b"Bearer"),
        ]})
        await send({"type": "http.response.body", "body": body})
