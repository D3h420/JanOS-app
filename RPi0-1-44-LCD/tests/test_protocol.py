"""Hardware-free contract tests for the ESP32-C5 serial transport."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import protocol  # noqa: E402


class FakeSerial:
    def __init__(self, initial: bytes = b"") -> None:
        self.input = bytearray(initial)
        self.output: list[bytes] = []
        self.is_open = True
        self.fail_read = False
        self.fail_write = False
        self.read_sizes: list[int] = []

    @property
    def in_waiting(self) -> int:
        if self.fail_read:
            raise OSError("USB odłączone")
        return len(self.input)

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        result = bytes(self.input[:size])
        del self.input[:size]
        return result

    def write(self, data: bytes) -> int:
        if self.fail_write:
            raise OSError("USB odłączone")
        self.output.append(data)
        return len(data)

    def close(self) -> None:
        self.is_open = False


class ProtocolTests(unittest.TestCase):
    def test_network_csv_parses_commas_quotes_and_hidden_ssid(self) -> None:
        network = protocol.parse_network_line(
            '"7","Cafe, \"\"East\"\"","Acme","aa:bb:cc:dd:ee:ff","6","WPA2","-63","2.4GHz"'
        )
        self.assertEqual(network, {
            "index": "7", "ssid": 'Cafe, "East"', "vendor": "Acme",
            "bssid": "aa:bb:cc:dd:ee:ff", "channel": "6", "auth": "WPA2",
            "rssi": "-63", "band": "2.4GHz",
        })
        self.assertEqual(
            protocol.parse_network_line('"1","","","00:00:00:00:00:00","1","open","-80","2.4GHz"')["ssid"],
            "<hidden>",
        )
        self.assertIsNone(protocol.parse_network_line("scan complete"))
        self.assertIsNone(protocol.parse_network_line('"1","only two"'))
        self.assertIsNone(protocol.parse_network_line('"unterminated'))

    def test_poll_opens_115200_8n1_and_assembles_partial_lines(self) -> None:
        serial = FakeSerial()
        arguments: list[dict] = []

        def factory(**kwargs):
            arguments.append(kwargs)
            return serial

        link = protocol.JanOSLink("/dev/ttyACM0", serial_factory=factory)
        self.assertEqual(link.poll(), [])
        self.assertTrue(link.connected)
        self.assertEqual(link.device, "/dev/ttyACM0")
        self.assertEqual(arguments[0], {
            "port": "/dev/ttyACM0", "baudrate": 115200, "bytesize": 8,
            "parity": "N", "stopbits": 1, "timeout": 0, "write_timeout": 0.2,
        })
        serial.input.extend(b"alpha\r\nbet")
        self.assertEqual(link.poll(), ["alpha"])
        serial.input.extend(b"a\ngamma\rdelta\r\n")
        self.assertEqual(link.poll(), ["beta", "gamma", "delta"])
        self.assertEqual(link.poll(), [])

    def test_poll_limits_work_even_with_large_available_input(self) -> None:
        serial = FakeSerial(b"x" * 5000 + b"\n")
        link = protocol.JanOSLink("/dev/ttyACM0", serial_factory=lambda **_: serial)
        self.assertEqual(link.poll(), [])
        self.assertEqual(len(serial.input), 905)
        self.assertEqual(link.poll(), ["x" * 5000])

    def test_read_failure_disconnects_and_next_poll_reconnects(self) -> None:
        first, second = FakeSerial(), FakeSerial(b"ready\n")
        serials = iter((first, second))
        link = protocol.JanOSLink(
            "/dev/ttyUSB0", serial_factory=lambda **_: next(serials), reconnect_interval=0,
        )
        self.assertEqual(link.poll(), [])
        first.input.extend(b"incomplete")
        self.assertEqual(link.poll(), [])
        first.fail_read = True
        self.assertEqual(link.poll(), [])
        self.assertFalse(link.connected)
        self.assertIsNone(link.device)
        self.assertIn("USB odłączone", link.error)
        self.assertTrue(first.is_open is False)
        self.assertEqual(link.poll(), ["ready"])
        self.assertTrue(link.connected)
        self.assertIsNone(link.error)

    def test_send_uses_crlf_and_recovers_from_write_error(self) -> None:
        first, second = FakeSerial(), FakeSerial()
        serials = iter((first, second))
        link = protocol.JanOSLink(
            "/dev/ttyUSB0", serial_factory=lambda **_: next(serials), reconnect_interval=0,
        )
        self.assertTrue(link.send("scan_networks"))
        self.assertEqual(first.output, [b"scan_networks\r\n"])
        first.fail_write = True
        self.assertFalse(link.send("stop"))
        self.assertFalse(link.connected)
        self.assertTrue(link.send("stop"))
        self.assertEqual(second.output, [b"stop\r\n"])
        self.assertFalse(link.send("stop\nreboot"))
        self.assertEqual(len(second.output), 1)

    def test_explicit_port_never_runs_autodetection(self) -> None:
        serial = FakeSerial()

        def no_scan():
            raise AssertionError("port enumeration should not run")

        link = protocol.JanOSLink(
            "/dev/serial/by-id/my-esp", serial_factory=lambda **_: serial,
            ports_provider=no_scan,
        )
        self.assertEqual(link.poll(), [])
        self.assertEqual(link.device, "/dev/serial/by-id/my-esp")

    def test_autodetection_prefers_stable_by_id_path(self) -> None:
        opened: list[str] = []

        def fake_glob(pattern: str) -> list[str]:
            if pattern == "/dev/serial/by-id/*":
                return ["/dev/serial/by-id/usb-Espressif_ESP32-C5"]
            return []

        def factory(**kwargs):
            opened.append(kwargs["port"])
            return FakeSerial()

        with patch.object(protocol.glob, "glob", side_effect=fake_glob):
            link = protocol.JanOSLink(
                serial_factory=factory,
                ports_provider=lambda: [SimpleNamespace(device="/dev/ttyACM0", description="USB CDC")],
            )
            link.poll()
        self.assertEqual(opened, ["/dev/serial/by-id/usb-Espressif_ESP32-C5"])

    def test_failed_by_id_open_falls_back_to_usb_device(self) -> None:
        opened: list[str] = []

        def fake_glob(pattern: str) -> list[str]:
            if pattern == "/dev/serial/by-id/*":
                return ["/dev/serial/by-id/usb-missing"]
            return []

        def factory(**kwargs):
            device = kwargs["port"]
            opened.append(device)
            if device.startswith("/dev/serial/by-id/"):
                raise OSError("stale symlink")
            return FakeSerial()

        with patch.object(protocol.glob, "glob", side_effect=fake_glob):
            link = protocol.JanOSLink(
                serial_factory=factory,
                ports_provider=lambda: [SimpleNamespace(device="/dev/ttyUSB0", description="CP210x")],
            )
            link.poll()
        self.assertEqual(opened, ["/dev/serial/by-id/usb-missing", "/dev/ttyUSB0"])
        self.assertEqual(link.device, "/dev/ttyUSB0")

    def test_missing_device_reports_error_without_exiting(self) -> None:
        with patch.object(protocol.glob, "glob", return_value=[]):
            link = protocol.JanOSLink(
                serial_factory=lambda **_: self.fail("factory must not run"),
                ports_provider=lambda: [], reconnect_interval=0,
            )
            self.assertEqual(link.poll(), [])
            self.assertFalse(link.connected)
            self.assertIn("Nie znaleziono", link.error)

    def test_close_releases_port_and_stops_reconnect(self) -> None:
        serial = FakeSerial()
        calls = 0

        def factory(**_):
            nonlocal calls
            calls += 1
            return serial

        link = protocol.JanOSLink("/dev/ttyACM0", serial_factory=factory)
        link.poll()
        link.close()
        self.assertFalse(serial.is_open)
        self.assertEqual(link.poll(), [])
        self.assertFalse(link.send("scan_networks"))
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
