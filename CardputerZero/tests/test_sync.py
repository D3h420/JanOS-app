import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "CardputerZero" / "scripts" / "sync_from_python.py"
GENERATED = ROOT / "CardputerZero" / "generated" / "command_catalog.json"


class CommandSyncTests(unittest.TestCase):
    def test_checked_in_catalog_is_current(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_generation_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"
            for output in (first, second):
                subprocess.run(
                    [sys.executable, str(SCRIPT), "--output", str(output)],
                    cwd=ROOT,
                    check=True,
                    text=True,
                    capture_output=True,
                )
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_manifest_has_fingerprint_and_manual_boundary(self):
        manifest = json.loads(GENERATED.read_text(encoding="utf-8"))
        self.assertRegex(manifest["fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn("JanOS_app.py", manifest["source_fingerprints"])
        self.assertIn("janos_core.py", manifest["source_fingerprints"])
        self.assertGreaterEqual(len(manifest["commands"]), 100)
        self.assertIsInstance(manifest["manual_porting"], list)
        self.assertTrue(
            all("reason" in item and "expression" in item for item in manifest["manual_porting"])
        )


if __name__ == "__main__":
    unittest.main()

