import base64
import struct
import sys
import types
import unittest
import zlib

# The protocol helpers under test do not open a port.  Keep the tests runnable
# in minimal CI environments where the optional runtime dependency is absent.
try:
    import serial  # noqa: F401
except ModuleNotFoundError:
    serial_module = types.ModuleType("serial")
    serial_module.tools = types.ModuleType("serial.tools")
    list_ports_module = types.ModuleType("serial.tools.list_ports")
    list_ports_module.comports = lambda: []
    serial_module.tools.list_ports = list_ports_module
    sys.modules["serial"] = serial_module
    sys.modules["serial.tools"] = serial_module.tools
    sys.modules["serial.tools.list_ports"] = list_ports_module

from JanOS_app import JanOS
from projectzero_commands import COMMAND_GROUPS, FILE_COMMANDS


class ProjectZeroCatalogTests(unittest.TestCase):
    def test_catalog_has_unique_commands(self):
        commands = [spec.command for group in COMMAND_GROUPS.values() for spec in group]
        self.assertEqual(len(commands), len(set(commands)))
        self.assertEqual(62, len(commands))

    def test_binary_file_commands_are_exposed(self):
        self.assertEqual(
            {"fs", "send_file", "uart_baud", "uart_baud_confirm", "uart_baud_status"},
            set(FILE_COMMANDS),
        )

    def test_fs_paths_use_cp437_base64(self):
        encoded = JanOS._fs_path64("pcaps/café.pcap")
        self.assertEqual("pcaps/café.pcap".encode("cp437"), base64.b64decode(encoded))
        with self.assertRaises(UnicodeEncodeError):
            JanOS._fs_path64("pcaps/żółć.pcap")

    def test_ack32_validation(self):
        frame = bytearray(32)
        frame[:4] = b"FTA\x01"
        frame[4:8] = struct.pack("<I", 7)
        frame[8] = 0x06
        frame[12:20] = struct.pack("<Q", 4096)
        frame[20:24] = struct.pack("<I", zlib.crc32(frame[:20]) & 0xFFFFFFFF)
        JanOS._validate_ack32(bytes(frame), 7, 4096)

        frame[8] = 0x15
        frame[20:24] = struct.pack("<I", zlib.crc32(frame[:20]) & 0xFFFFFFFF)
        with self.assertRaises(RuntimeError):
            JanOS._validate_ack32(bytes(frame), 7, 4096)


if __name__ == "__main__":
    unittest.main()
