import json
import tempfile
import unittest
from pathlib import Path

from app.model_store import model_location, snapshot_ready, write_manifest

MODEL = "example/instruct"
REVISION = "a" * 40


class SnapshotTests(unittest.TestCase):
    def make_snapshot(self, directory):
        (directory / "config.json").write_text("{}")
        (directory / "tokenizer_config.json").write_text("{}")
        (directory / "model.safetensors").write_bytes(b"weights")
        write_manifest(directory, MODEL, REVISION)

    def test_partial_snapshot_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "config.json").write_text("{}")
            self.assertFalse(snapshot_ready(directory, MODEL, REVISION))

    def test_same_size_corruption_and_changed_revision_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_snapshot(directory)
            self.assertTrue(snapshot_ready(directory, MODEL, REVISION))
            self.assertFalse(snapshot_ready(directory, MODEL, "b" * 40))
            (directory / "model.safetensors").write_bytes(b"corrupt")
            self.assertFalse(snapshot_ready(directory, MODEL, REVISION))

    def test_manifest_cannot_read_outside_the_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_snapshot(directory)
            marker = directory / ".complete.json"
            data = json.loads(marker.read_text())
            data["files"]["../outside"] = {"size": 0, "sha256": ""}
            marker.write_text(json.dumps(data))
            self.assertFalse(snapshot_ready(directory, MODEL, REVISION))

    def test_mutable_revision_is_rejected(self):
        with self.assertRaises(ValueError):
            model_location(Path("/models"), MODEL, "main")


if __name__ == "__main__":
    unittest.main()
