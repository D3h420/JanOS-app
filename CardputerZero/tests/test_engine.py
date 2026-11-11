import tempfile
import time
import unittest
from pathlib import Path

from CardputerZero.app.engine import JanOSEngine, load_catalog


class CardputerEngineTests(unittest.TestCase):
    def test_generated_catalog_is_complete_and_unique_by_command(self):
        catalog = load_catalog()
        commands = {entry.command for entry in catalog}
        self.assertGreaterEqual(len(commands), 130)
        self.assertIn("scan_networks", commands)
        self.assertIn("capture_gateway", commands)
        self.assertIn("start_zig_recon", commands)
        self.assertIn("fs", commands)

    def test_demo_command_emits_results_and_finishes(self):
        engine = JanOSEngine(demo=True)
        operation = engine.start_command("version")
        operation.thread.join(timeout=2)
        events = operation.poll()
        self.assertEqual("done", operation.state)
        self.assertTrue(any(event.kind == "line" for event in events))
        self.assertTrue(any(event.kind == "finished" for event in events))
        engine.close()

    def test_demo_file_download_creates_real_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = JanOSEngine(demo=True)
            engine.data_dir = Path(directory)
            operation = engine.download("pcaps/demo.pcap")
            operation.thread.join(timeout=2)
            self.assertEqual("done", operation.state)
            self.assertEqual(b"SIMULATED\n", (Path(directory) / "downloads" / "demo.pcap").read_bytes())


if __name__ == "__main__":
    unittest.main()
