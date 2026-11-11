import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from janos_core import (
    crc32_file,
    fs_path64,
    make_ftb_frame,
    parse_firmware_version,
    parse_ftb_header,
    parse_help_commands,
    parse_network_line,
    parse_fta_frame,
    validate_fta_frame,
)


class JanOSCoreTests(unittest.TestCase):
    def test_scan_csv_parser_handles_commas(self):
        record = parse_network_line('"2","Cafe, WiFi","","AA:BB:CC:DD:EE:FF","6","WPA2","-51","2.4GHz"')
        self.assertEqual("Cafe, WiFi", record.ssid)
        self.assertEqual("", record.vendor)
        self.assertEqual("AA:BB:CC:DD:EE:FF", record.bssid)

    def test_capability_parsers(self):
        self.assertEqual("1.7.6", parse_firmware_version(["JanOS version: 1.7.6"]))
        commands = parse_help_commands(["scan_networks  Scan Wi-Fi", "stop  Stop all"], {"scan_networks", "stop"})
        self.assertEqual({"scan_networks", "stop"}, commands)

    def test_fs_paths_reject_traversal(self):
        self.assertTrue(fs_path64("pcaps/a.pcap"))
        with self.assertRaises(ValueError):
            fs_path64("../secret")

    def test_ftb_and_fta_frames(self):
        frame = make_ftb_frame(3, b"hello")
        self.assertEqual((3, 5, zlib.crc32(b"hello") & 0xFFFFFFFF), parse_ftb_header(frame[:16]))
        ack = bytearray(32)
        ack[:4] = b"FTA\x01"
        ack[4:8] = struct.pack("<I", 3)
        ack[8] = 0x06
        ack[12:20] = struct.pack("<Q", 5)
        ack[20:24] = struct.pack("<I", zlib.crc32(ack[:20]) & 0xFFFFFFFF)
        validate_fta_frame(bytes(ack), 3, 5)
        self.assertEqual((3, 0x06, 5), parse_fta_frame(bytes(ack)))

    def test_file_crc_is_streaming_and_supports_prefixes(self):
        payload = b"JanOS\0" * 1000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wordlist.bin"
            path.write_bytes(payload)
            self.assertEqual((len(payload), zlib.crc32(payload) & 0xFFFFFFFF), crc32_file(path))
            self.assertEqual((23, zlib.crc32(payload[:23]) & 0xFFFFFFFF), crc32_file(path, limit=23))


if __name__ == "__main__":
    unittest.main()
