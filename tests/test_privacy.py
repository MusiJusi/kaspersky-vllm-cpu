import asyncio
import io
import json
import logging
import unittest

from app.audit import RequestAuditMiddleware
from app.safe_logging import SafeJsonFormatter


class PrivacyTests(unittest.TestCase):
    def test_upstream_messages_arguments_and_tracebacks_are_not_rendered(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(SafeJsonFormatter())
        logger = logging.Logger("vllm.third_party")
        logger.addHandler(handler)
        secret = "PROMPT_AND_ANSWER_MUST_REMAIN_PRIVATE"
        try:
            raise ValueError(secret)
        except ValueError:
            logger.exception("request: %s", secret, stack_info=True)
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["event"], "runtime_log")

    def test_streaming_request_logs_only_server_generated_metadata(self):
        output = io.StringIO()
        logger = logging.getLogger("app.audit")
        old_handlers, old_level, old_propagate = logger.handlers[:], logger.level, logger.propagate
        handler = logging.StreamHandler(output)
        handler.setFormatter(SafeJsonFormatter())
        logger.handlers, logger.level, logger.propagate = [handler], logging.INFO, False
        secret = "PRIVATE_BODY_QUERY_HEADER_PATH_AND_ANSWER"
        messages = []

        async def endpoint(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": secret.encode(), "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        async def receive():
            return {"type": "http.request", "body": secret.encode()}

        async def send(message):
            messages.append(message)

        try:
            asyncio.run(RequestAuditMiddleware(endpoint)(
                {"type": "http", "method": "POST", "path": "/" + secret,
                 "query_string": secret.encode(), "headers": [(b"authorization", secret.encode()), (b"x-request-id", secret.encode())]},
                receive, send,
            ))
        finally:
            logger.handlers, logger.level, logger.propagate = old_handlers, old_level, old_propagate
        self.assertNotIn(secret, output.getvalue())
        data = json.loads(output.getvalue())
        self.assertEqual(data["event"], "http_request")
        self.assertEqual(data["status"], 200)
        self.assertEqual(data["route"], "other")
        self.assertEqual(len(data["request_id"]), 32)
        self.assertGreaterEqual(data["duration_ms"], 0)
        self.assertEqual(messages[0]["headers"][0][0], b"x-request-id")


if __name__ == "__main__":
    unittest.main()
