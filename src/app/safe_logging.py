"""Fail-closed JSON logging: arbitrary upstream messages are never rendered."""

import json
import logging
import os
import time

EVENTS = {"http_request", "service_start", "service_config_error", "runtime_failure"}
ROUTES = {"/v1/chat/completions", "/v1/completions", "/v1/models", "/health", "/metrics", "other"}
METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "other"}


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "event": "runtime_log",
        }
        # Do not call getMessage(), formatException(), or formatStack(). A prompt
        # can appear in third-party error messages, arguments and tracebacks.
        if record.name == "app.audit" and getattr(record, "event", None) in EVENTS:
            data["event"] = record.event
            if record.event == "http_request":
                data.update(
                    request_id=record.request_id,
                    method=record.method if record.method in METHODS else "other",
                    route=record.route if record.route in ROUTES else "other",
                    status=int(record.status),
                    duration_ms=round(float(record.duration_ms), 3),
                )
        else:
            # Retain a location for diagnosis, without serialising message data.
            data["source"] = f"{record.filename}:{record.lineno}"
        if record.exc_info and record.exc_info[0]:
            data["error_type"] = record.exc_info[0].__name__
            traceback = record.exc_info[2]
            if traceback:
                while traceback.tb_next:
                    traceback = traceback.tb_next
                data["error_source"] = f"{os.path.basename(traceback.tb_frame.f_code.co_filename)}:{traceback.tb_lineno}"
                data["error_module"] = traceback.tb_frame.f_globals.get("__name__", "unknown")
        return json.dumps(data, ensure_ascii=True, allow_nan=False)
