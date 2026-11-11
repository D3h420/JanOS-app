import tempfile
import struct
import os
import time
import unittest
import zlib
from collections import deque
from pathlib import Path
from unittest.mock import patch

from CardputerZero.app.engine import JanOSEngine, load_catalog


def ack32(index, status, offset):
    frame = bytearray(32)
    frame[:4] = b"FTA\x01"
    frame[4:8] = struct.pack("<I", index)
    frame[8] = status
    frame[12:20] = struct.pack("<Q", offset)
    frame[20:24] = struct.pack("<I", zlib.crc32(frame[:20]) & 0xFFFFFFFF)
    return bytes(frame)


class CrackSerial:
    def __init__(self, size, crc):
        self.is_open = True
        self.size = size
        self.crc = crc
        self.lines = deque()
        self.binary = bytearray()
        self.frames = []
        self.committed = 0

    def reset_input_buffer(self): pass
    def reset_output_buffer(self): pass
    def flush(self): pass
    def close(self): self.is_open = False

    def write(self, data):
        if data.startswith(b"crack_worker receive"):
            self.lines.extend([
                (
                    f"[CRACK/1] READY kind=wordlist size={self.size} crc32={self.crc:08X} "
                    "offset=0 prefix_crc=00000000 bsize=1024 rx_ms=8000 ack_size=32 "
                    "ack_wait_ms=2000 prepare_ms=10000\r\n"
                ).encode(),
                b"[CRACK/1] END\r\n",
            ])
        elif data.startswith(b"FTB\x01"):
            index, length, _ = struct.unpack("<III", data[4:16])
            self.frames.append((index, length))
            if length:
                self.committed += length
            self.binary.extend(ack32(index, 0x06, self.committed))
        elif data == b"\x18":
            self.lines.extend([
                b"[CRACK/1] SYNCED kind=wordlist\r\n",
                b"[CRACK/1] END\r\n",
            ])
        return len(data)

    def readline(self):
        return self.lines.popleft() if self.lines else b""

    def read(self, size):
        chunk = bytes(self.binary[:size])
        del self.binary[:size]
        return chunk


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

    def test_demo_crack_upload_uses_managed_upload_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = JanOSEngine(demo=True)
            engine.data_dir = Path(directory)
            uploads = Path(directory) / "uploads"
            uploads.mkdir()
            (uploads / "words.txt").write_text("password\n", encoding="utf-8")
            operation = engine.crack_upload("words.txt", "wordlist")
            operation.thread.join(timeout=2)
            events = operation.poll()
            self.assertEqual("done", operation.state)
            self.assertTrue(any("CRC32=" in event.message for event in events))
            self.assertTrue(any("synchronized" in event.message for event in events))

    def test_crack_upload_runs_ack32_binary_protocol(self):
        payload = b"candidate\n" * 170
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "words.txt"
            source.write_bytes(payload)
            checksum = zlib.crc32(payload) & 0xFFFFFFFF
            with patch.dict(os.environ, {"JANOS_CARDPUTER_STATE_DIR": directory}):
                engine = JanOSEngine()
            engine.serial = CrackSerial(len(payload), checksum)
            engine.device = "/dev/fake"
            operation = engine.crack_upload(str(source), "wordlist")
            operation.thread.join(timeout=3)
            events = operation.poll()
            self.assertEqual("done", operation.state, [event.message for event in events])
            self.assertEqual([(0, 1024), (1, len(payload) - 1024), (2, 0)], engine.serial.frames)
            self.assertTrue(any("SYNCED" in event.message for event in events))


if __name__ == "__main__":
    unittest.main()
