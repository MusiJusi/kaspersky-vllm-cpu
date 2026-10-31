"""Translate a ConfigMap into vLLM arguments, enforcing privacy invariants."""

import json
import logging
import logging.config
import os
import sys
from pathlib import Path

from app.model_store import model_location, snapshot_ready

INTEGER_OPTIONS = {"max_model_len", "max_num_seqs", "max_num_batched_tokens"}
BOOLEAN_OPTIONS = {"enable_prefix_caching", "enable_chunked_prefill", "enforce_eager"}
ALLOWED_OPTIONS = INTEGER_OPTIONS | BOOLEAN_OPTIONS | {"dtype", "served_model_name"}


def inference_arguments(settings: dict) -> list[str]:
    if not isinstance(settings, dict) or settings.keys() - ALLOWED_OPTIONS:
        raise ValueError("Unsupported inference configuration.")
    arguments = []
    for key, value in settings.items():
        flag = "--" + key.replace("_", "-")
        if key in INTEGER_OPTIONS:
            if type(value) is not int or value <= 0:
                raise ValueError("Inference limits must be positive integers.")
            arguments.extend([flag, str(value)])
        elif key in BOOLEAN_OPTIONS:
            if type(value) is not bool:
                raise ValueError("Inference toggles must be booleans.")
            arguments.append(flag if value else "--no-" + key.replace("_", "-"))
        elif key == "dtype":
            if value not in {"float32", "float16", "bfloat16", "auto"}:
                raise ValueError("Unsupported dtype.")
            arguments.extend([flag, value])
        else:
            if not isinstance(value, str) or not value or len(value) > 100:
                raise ValueError("Invalid served model name.")
            arguments.extend([flag, value])
    return arguments


def main() -> int:
    logging_path = os.environ.get("VLLM_LOGGING_CONFIG_PATH", "/app/config/logging.json")
    logging.config.dictConfig(json.loads(Path(logging_path).read_text(encoding="utf-8")))
    logger = logging.getLogger("app.audit")
    try:
        token = os.environ.get("VLLM_API_KEY", "")
        if len(token) < 32 or token.strip() != token:
            raise ValueError("A non-empty API token of at least 32 characters is required.")
        model_id = os.environ["MODEL_ID"]
        revision = os.environ["MODEL_REVISION"]
        model_path = model_location(Path(os.environ.get("MODEL_ROOT", "/models")), model_id, revision)
        if not snapshot_ready(model_path, model_id, revision):
            raise ValueError("No complete local model snapshot is available.")
        settings = json.loads(Path(os.environ.get("INFERENCE_CONFIG", "/config/inference.json")).read_text(encoding="utf-8"))
        command = [
            sys.executable, "-m", "vllm.entrypoints.openai.api_server",
            "--host", "0.0.0.0", "--port", "8000",
            "--model", str(model_path),
            *inference_arguments(settings),
            "--no-enable-log-requests", "--no-enable-log-outputs", "--no-log-error-stack",
            "--disable-uvicorn-access-log",
            "--middleware", "app.audit.RequestAuditMiddleware",
            "--log-config-file", logging_path,
        ]
        os.environ.update({
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "VLLM_NO_USAGE_STATS": "1", "DO_NOT_TRACK": "1",
            "VLLM_DEBUG_LOG_API_SERVER_RESPONSE": "0", "VLLM_SERVER_DEV_MODE": "0",
            "VLLM_LOGGING_LEVEL": "INFO", "VLLM_TARGET_DEVICE": "cpu",
        })
        os.environ.pop("HF_TOKEN", None)
        logger.info("service_start", extra={"event": "service_start"})
        os.execv(sys.executable, command)
    except Exception:
        logger.error("service_config_error", extra={"event": "service_config_error"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
