"""Download once into PVC; subsequent invocations are entirely local."""

import fcntl
import json
import os
import sys
from pathlib import Path

from app.model_store import model_location, snapshot_ready, write_manifest


def download(root: Path, model_id: str, revision: str) -> str:
    destination = model_location(root, model_id, revision)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".download.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if snapshot_ready(destination, model_id, revision):
            return "model_cache_hit"
        if destination.exists():
            raise RuntimeError("Existing completed snapshot is corrupt; restore it or use a fresh model volume.")
        staging = destination.with_name(destination.name + ".partial")
        staging.mkdir(parents=True, exist_ok=True)

        # Import after the cache check: the cached path cannot call the HF API.
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=model_id,
            revision=revision,
            local_dir=staging,
            token=os.environ.get("HF_TOKEN") or False,
            allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.jinja"],
            max_workers=4,
        )
        write_manifest(staging, model_id, revision)
        staging.rename(destination)
        return "model_download_complete"


def main() -> int:
    try:
        event = download(
            Path(os.environ.get("MODEL_ROOT", "/models")),
            os.environ["MODEL_ID"],
            os.environ["MODEL_REVISION"],
        )
        print(json.dumps({"event": event}), flush=True)
        return 0
    except Exception as error:
        # HF exception strings can contain request URLs and authentication data.
        print(json.dumps({"event": "model_download_failed", "error_type": type(error).__name__}), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
