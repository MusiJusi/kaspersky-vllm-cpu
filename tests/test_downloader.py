"""Linux-only integration checks of the cache shortcut and interrupted downloads."""

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.model_store import model_location, write_manifest

MODEL = "example/instruct"
REVISION = "a" * 40


@unittest.skipUnless(importlib.util.find_spec("fcntl"), "Downloader file locking requires Linux.")
class DownloaderTests(unittest.TestCase):
    def test_ready_cache_does_not_import_or_call_huggingface(self):
        from app.download_model import download

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = model_location(root, MODEL, REVISION)
            destination.mkdir(parents=True)
            (destination / "config.json").write_text("{}")
            (destination / "tokenizer_config.json").write_text("{}")
            (destination / "model.safetensors").write_bytes(b"weights")
            write_manifest(destination, MODEL, REVISION)
            with patch.dict(sys.modules, {"huggingface_hub": None}):
                self.assertEqual(download(root, MODEL, REVISION), "model_cache_hit")

    def test_interrupted_download_never_appears_as_complete(self):
        from app.download_model import download

        def interrupted_download(**kwargs):
            (Path(kwargs["local_dir"]) / "model.safetensors").write_bytes(b"partial")
            raise OSError("simulated connection interruption")

        fake_hub = types.SimpleNamespace(snapshot_download=interrupted_download)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict(sys.modules, {"huggingface_hub": fake_hub}):
                with self.assertRaises(OSError):
                    download(root, MODEL, REVISION)
            destination = model_location(root, MODEL, REVISION)
            self.assertFalse(destination.exists())
            self.assertTrue(destination.with_name(destination.name + ".partial").exists())


if __name__ == "__main__":
    unittest.main()
