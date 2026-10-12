"""Nonblocking USB serial link to the JanOS ESP32-C5 firmware.

The display UI calls :meth:`JanOSLink.poll` from its event loop.  No serial
read waits for a complete line, so a slow scan cannot stall button handling.
"""

from __future__ import annotations

import csv
import glob
import time
from typing import Callable, Iterable


BAUD_RATE = 115200
_READ_BUDGET = 4096
_MAX_LINE_BYTES = 16384


def parse_network_line(line: str) -> dict[str, str] | None:
    """Parse the eight quoted Wi-Fi fields emitted by the existing firmware.

    A CSV parser is needed because an SSID may contain a comma or an escaped
    quote.  Fields match ``NetworkManager.parse_network_line`` in JanOS_app.py.
    """
    if not line.startswith('"'):
        return None
    try:
        fields = next(csv.reader([line], strict=True))
    except (csv.Error, StopIteration):
        return None
    if len(fields) < 8:
        return None
    return dict(zip(
        ("index", "ssid", "vendor", "bssid", "channel", "auth", "rssi", "band"),
        (fields[0], fields[1] or "<hidden>", *fields[2:8]),
    ))


def _default_ports_provider() -> Iterable[object]:
    from serial.tools import list_ports

    return list_ports.comports()


def _port_score(device: str, details: str = "") -> int:
    """Select USB serial ports, excluding the Pi's on-board UARTs."""
    name = device.lower()
    details = details.lower()
    if name.startswith("/dev/serial/by-id/"):
        base = 300
    elif name.startswith(("/dev/ttyusb", "/dev/ttyacm", "/dev/cu.usb", "/dev/cu.slab", "/dev/cu.wch")):
        base = 100
    elif name.startswith(("/dev/tty.usb", "/dev/tty.slab", "/dev/tty.wch")):
        base = 80
    else:
        return -1
    if any(word in name + " " + details for word in (
        "espressif", "esp32", "cp210", "ch340", "ch910", "ftdi", "usb_serial", "usb-serial",
    )):
        base += 20
    return base


class JanOSLink:
    """An event-loop friendly serial connection with automatic reconnection.

    ``port`` pins an explicit device. Otherwise the stable Linux
    ``/dev/serial/by-id`` paths are preferred, followed by USB UART device
    nodes reported by pyserial or found by globbing. ``serial_factory`` and
    ``ports_provider`` can be injected for tests.
    """

    def __init__(
        self,
        port: str | None = None,
        *,
        serial_factory: Callable[..., object] | None = None,
        ports_provider: Callable[[], Iterable[object]] | None = None,
        reconnect_interval: float = 1.0,
    ) -> None:
        self._requested_port = port
        self._serial_factory = serial_factory
        self._ports_provider = ports_provider or _default_ports_provider
        self._reconnect_interval = max(0.0, reconnect_interval)
        self._serial: object | None = None
        self._device: str | None = None
        self._error: str | None = None
        self._last_attempt: float | None = None
        self._line = bytearray()
        self._discard_long_line = False
        self._closed = False

    @property
    def connected(self) -> bool:
        if self._serial is None:
            return False
        try:
            return bool(getattr(self._serial, "is_open", True))
        except Exception:
            return False

    @property
    def device(self) -> str | None:
        return self._device if self.connected else None

    @property
    def error(self) -> str | None:
        return self._error

    def _candidates(self) -> list[str]:
        if self._requested_port:
            return [self._requested_port]

        scores: dict[str, int] = {}

        def add(device: str, details: str = "") -> None:
            score = _port_score(device, details)
            if score >= 0:
                scores[device] = max(score, scores.get(device, -1))

        for device in glob.glob("/dev/serial/by-id/*"):
            add(device)

        # list_ports supplies metadata on most adapters but some Linux drivers
        # expose only a device node, so keep the simple glob fallback too.
        try:
            ports = self._ports_provider()
            for port in ports:
                if isinstance(port, str):
                    add(port)
                else:
                    device = getattr(port, "device", None)
                    if device:
                        details = " ".join(str(getattr(port, key, "") or "") for key in (
                            "description", "manufacturer", "product", "hwid",
                        ))
                        add(device, details)
        except Exception:
            # Device-node discovery still works when enumeration fails.
            pass

        for pattern in (
            "/dev/ttyUSB*", "/dev/ttyACM*", "/dev/cu.usb*", "/dev/cu.SLAB*",
            "/dev/cu.wch*", "/dev/tty.usb*", "/dev/tty.SLAB*", "/dev/tty.wch*",
        ):
            for device in glob.glob(pattern):
                add(device)

        return sorted(scores, key=lambda device: (-scores[device], device))

    def _connect(self) -> None:
        if self._closed or self.connected:
            return
        now = time.monotonic()
        if self._last_attempt is not None and now - self._last_attempt < self._reconnect_interval:
            return
        self._last_attempt = now

        factory = self._serial_factory
        if factory is None:
            try:
                import serial
            except ModuleNotFoundError:
                self._error = "Brak pyserial; zainstaluj: python3 -m pip install pyserial"
                return
            factory = serial.Serial

        candidates = self._candidates()
        if not candidates:
            self._error = "Nie znaleziono portu USB ESP32-C5"
            return

        for device in candidates:
            try:
                connection = factory(
                    port=device,
                    baudrate=BAUD_RATE,
                    bytesize=8,
                    parity="N",
                    stopbits=1,
                    timeout=0,
                    write_timeout=0.2,
                )
                if not getattr(connection, "is_open", True):
                    raise OSError("Port został zamknięty")
            except Exception as exc:
                self._error = f"{device}: {exc}"
                continue
            self._serial = connection
            self._device = device
            self._error = None
            self._line.clear()
            self._discard_long_line = False
            return

    def _disconnect(self, reason: Exception | str) -> None:
        connection = self._serial
        self._serial = None
        self._device = None
        self._error = str(reason)
        self._line.clear()
        self._discard_long_line = False
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _consume(self, data: bytes) -> list[str]:
        lines: list[str] = []
        for byte in data:
            if byte in (10, 13):
                if self._line and not self._discard_long_line:
                    line = self._line.decode("utf-8", errors="replace").strip()
                    if line:
                        lines.append(line)
                self._line.clear()
                self._discard_long_line = False
            elif not self._discard_long_line:
                if len(self._line) == _MAX_LINE_BYTES:
                    self._line.clear()
                    self._discard_long_line = True
                else:
                    self._line.append(byte)
        return lines

    def poll(self) -> list[str]:
        """Read available complete lines without waiting for incoming bytes."""
        if self._closed:
            return []
        if self._serial is not None and not self.connected:
            self._disconnect("Port został zamknięty")
        self._connect()
        if not self.connected:
            return []

        lines: list[str] = []
        remaining = _READ_BUDGET
        try:
            while remaining:
                waiting = self._serial.in_waiting
                if not waiting:
                    break
                chunk = self._serial.read(min(waiting, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                lines.extend(self._consume(chunk))
        except Exception as exc:
            self._disconnect(exc)
        return lines

    def send(self, command: str) -> bool:
        """Write one JanOS command with CRLF; return success or failure."""
        if self._closed:
            return False
        if self._serial is not None and not self.connected:
            self._disconnect("Port został zamknięty")
        self._connect()
        if not self.connected:
            return False
        if not isinstance(command, str) or "\r" in command or "\n" in command:
            self._error = "Polecenie musi być pojedynczą linią tekstu"
            return False
        payload = (command + "\r\n").encode("utf-8")
        try:
            written = self._serial.write(payload)
            if written != len(payload):
                raise OSError("Niepełny zapis do portu szeregowego")
            return True
        except Exception as exc:
            self._disconnect(exc)
            return False

    def close(self) -> None:
        """Release the port and stop future reconnect attempts."""
        self._closed = True
        self._disconnect("Połączenie zamknięte")
