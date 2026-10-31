"""A completed, immutable model snapshot shared by init and serving containers."""

import hashlib
import json
import os
import re
from pathlib import Path

MANIFEST = ".complete.json"


def model_location(root: Path, model_id: str, revision: str) -> Path:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", model_id, flags=re.ASCII):
        raise ValueError("Model ID must have the form owner/name.")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Model revision must be a full 40-character commit SHA.")
    return root / model_id.replace("/", "--") / revision


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(directory: Path, model_id: str, revision: str) -> None:
    files = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if relative.parts[0] == ".cache" or relative.name in {MANIFEST, MANIFEST + ".tmp"}:
            continue
        if path.is_symlink():
            raise ValueError("Model snapshots must not contain symbolic links.")
        if path.is_file():
            files[relative.as_posix()] = {
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    if "config.json" not in files or "tokenizer_config.json" not in files:
        raise ValueError("The downloaded model is missing configuration files.")
    if not any(name.endswith(".safetensors") for name in files):
        raise ValueError("The downloaded model is missing safetensors weights.")
    temporary = directory / (MANIFEST + ".tmp")
    temporary.write_text(
        json.dumps({"model_id": model_id, "revision": revision, "files": files}),
        encoding="utf-8",
    )
    os.replace(temporary, directory / MANIFEST)


def snapshot_ready(directory: Path, model_id: str, revision: str) -> bool:
    """Validate the local snapshot without importing HF or making network calls."""
    try:
        data = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
        if data["model_id"] != model_id or data["revision"] != revision:
            return False
        files = data["files"]
        if "config.json" not in files or "tokenizer_config.json" not in files:
            return False
        if not any(name.endswith(".safetensors") for name in files):
            return False
        for name, expected in files.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                return False
            path = directory / relative
            if path.is_symlink() or not path.is_file():
                return False
            if path.stat().st_size != expected["size"]:
                return False
            if sha256_file(path) != expected["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False
