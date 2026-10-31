import os
import unittest
from unittest.mock import patch

from app.auth import BearerAuthMiddleware

TOKEN = "test-token-for-authentication-123456789"


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, path, authorization=None):
        messages = []
        called = []

        async def endpoint(scope, receive, send):
            called.append(True)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            messages.append(message)

        with patch.dict(os.environ, {"VLLM_API_KEY": TOKEN}):
            middleware = BearerAuthMiddleware(endpoint)
        headers = [(b"authorization", authorization)] if authorization else []
        await middleware({"type": "http", "method": "GET", "path": path, "headers": headers}, receive, send)
        return called, messages[0]["status"]

    async def test_all_model_routes_require_authentication(self):
        for path in ("/v1/chat/completions", "/invocations", "/tokenize", "/score"):
            for authorization in (None, b"Bearer invalid-token"):
                with self.subTest(path=path, credential=authorization):
                    called, status = await self.exercise(path, authorization)
                    self.assertFalse(called)
                    self.assertEqual(status, 401)

    async def test_valid_token_allows_access(self):
        called, status = await self.exercise("/v1/models", b"bEaReR " + TOKEN.encode())
        self.assertTrue(called)
        self.assertEqual(status, 200)

    async def test_health_probe_does_not_require_a_token(self):
        called, status = await self.exercise("/health")
        self.assertTrue(called)
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
