"""Non-blocking JanOS engine used by the Cardputer Zero UI."""

from __future__ import annotations

import json
import os
import queue
import re
import struct
import tempfile
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from janos_core import (
    fs_path64,
    make_ftb_finish,
    make_ftb_frame,
    parse_firmware_version,
    parse_ftb_header,
    parse_help_commands,
    parse_network_line,
    validate_fta_frame,
)
from projectzero_commands import COMMAND_GROUPS, FILE_COMMANDS, SHARED_COMMAND_GROUPS


@dataclass(frozen=True)
class CatalogEntry:
    command: str
    label: str
    group: str
    arguments: str = ""
    stream: bool = False
    confirm: bool = False


@dataclass(frozen=True)
class EngineEvent:
    kind: str
    message: str
    payload: object | None = None


@dataclass
class Operation:
    command: str
    events: queue.Queue[EngineEvent] = field(default_factory=queue.Queue)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    state: str = "running"

    def poll(self) -> list[EngineEvent]:
        output = []
        while True:
            try:
                output.append(self.events.get_nowait())
            except queue.Empty:
                return output

    def cancel(self) -> None:
        self.cancel_event.set()


def _generated_catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "generated" / "command_catalog.json"


def load_catalog() -> tuple[CatalogEntry, ...]:
    path = _generated_catalog_path()
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = []
        for item in raw["commands"]:
            groups = item.get("groups") or ["Python workflows"]
            for group in groups:
                entries.append(CatalogEntry(
                    command=item["command"],
                    label=item.get("label") or item["command"].replace("_", " ").title(),
                    group=group,
                    arguments=item.get("arguments", ""),
                    stream=bool(item.get("stream")),
                    confirm=bool(item.get("confirm")),
                ))
        return tuple(entries)
    # Developer fallback before the first sync. The build always generates it.
    entries = []
    groups = dict(COMMAND_GROUPS)
    groups.update(SHARED_COMMAND_GROUPS)
    for group, specs in groups.items():
        entries.extend(
            CatalogEntry(spec.command, spec.label, group, spec.arguments, spec.stream, spec.confirm)
            for spec in specs
        )
    entries.extend(CatalogEntry(command, command, "Files and UART") for command in FILE_COMMANDS)
    return tuple(entries)


class JanOSEngine:
    def __init__(self, *, demo: bool = False) -> None:
        self.demo = demo
        self.catalog = load_catalog()
        self.serial = None
        self.device = "DEMO" if demo else ""
        self.baud_rate = 115200
        self.firmware_version = "demo-1.7.6" if demo else "unknown"
        self.available_commands: set[str] = {entry.command for entry in self.catalog} if demo else set()
        self._lock = threading.RLock()
        self._active: Operation | None = None
        state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        default_state = Path(tempfile.gettempdir()) / "janos-cardputer-demo" if demo else state_home / "janos-cardputer"
        self.data_dir = Path(os.environ.get("JANOS_CARDPUTER_STATE_DIR", default_state))
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def ports(self) -> list[str]:
        if self.demo:
            return ["DEMO /dev/ttyUSB0", "DEMO /dev/ttyAMA0"]
        from serial.tools import list_ports
        candidates = []
        for item in list_ports.comports():
            text = " ".join(filter(None, (item.device, item.description, item.manufacturer)))
            score = 2 if any(token in text.lower() for token in ("usb", "cp210", "ch340", "uart", "esp32")) else 1
            candidates.append((score, item.device))
        for fixed in ("/dev/serial0", "/dev/ttyAMA0"):
            if os.path.exists(fixed) and all(device != fixed for _, device in candidates):
                candidates.append((1, fixed))
        return [device for _, device in sorted(candidates, key=lambda item: (-item[0], item[1]))]

    @property
    def connected(self) -> bool:
        return self.demo or bool(self.serial and self.serial.is_open)

    def connect(self, device: str) -> None:
        self.disconnect()
        if self.demo:
            self.device = device
            return
        import serial
        self.serial = serial.Serial(
            device,
            self.baud_rate,
            timeout=0.15,
            write_timeout=2,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
        self.device = device

    def disconnect(self) -> None:
        if self._active and self._active.state == "running":
            self._active.cancel()
        if self.serial:
            try:
                self.serial.close()
            except Exception:
                pass
        self.serial = None
        if not self.demo:
            self.device = ""

    def close(self) -> None:
        self.disconnect()

    def _write_command(self, command: str) -> None:
        if not self.connected:
            raise RuntimeError("MonsterC5 is not connected")
        if self.demo:
            return
        assert self.serial
        self.serial.write((command + "\r\n").encode("utf-8"))
        self.serial.flush()

    def _read_lines(self, max_wait: float, idle: float, emit: Callable[[str], None]) -> list[str]:
        if self.demo:
            return []
        assert self.serial
        lines: list[str] = []
        started = last = time.monotonic()
        while time.monotonic() - started < max_wait:
            raw = self.serial.readline()
            if raw:
                text = raw.decode("utf-8", errors="replace").strip()
                if text:
                    lines.append(text)
                    emit(text)
                    last = time.monotonic()
            elif lines and time.monotonic() - last >= idle:
                break
        return lines

    def probe(self) -> None:
        if self.demo:
            return
        with self._lock:
            assert self.serial
            self.serial.reset_input_buffer()
            self._write_command("version")
            version = self._read_lines(4, 0.5, lambda _line: None)
            self.firmware_version = parse_firmware_version(version)
            self._write_command("help")
            help_lines = self._read_lines(10, 0.8, lambda _line: None)
            known = {entry.command for entry in self.catalog}
            self.available_commands = parse_help_commands(help_lines, known)

    def start_command(
        self,
        command: str,
        *,
        stream: bool = False,
        stop_command: str = "stop",
        max_wait: float = 120,
    ) -> Operation:
        if self._active and self._active.state == "running":
            raise RuntimeError("Another UART operation is already running")
        operation = Operation(command)
        self._active = operation

        def worker() -> None:
            try:
                if self.demo:
                    operation.events.put(EngineEvent("line", f"[SIMULATED] UART -> {command}"))
                    for number in range(3):
                        if operation.cancel_event.wait(0.15):
                            break
                        operation.events.put(EngineEvent("line", f"[SIMULATED] result {number + 1}"))
                    return
                with self._lock:
                    assert self.serial
                    self.serial.reset_input_buffer()
                    self._write_command(command)
                    started = last = time.monotonic()
                    while not operation.cancel_event.is_set():
                        raw = self.serial.readline()
                        if raw:
                            line = raw.decode("utf-8", errors="replace").strip()
                            if line and line != command and not line.startswith(">"):
                                operation.events.put(EngineEvent("line", line))
                                last = time.monotonic()
                        elif not stream and time.monotonic() - last >= 1.0:
                            break
                        if not stream and time.monotonic() - started >= max_wait:
                            break
                    if operation.cancel_event.is_set() and stream:
                        self._write_command(stop_command)
            except Exception as error:
                operation.events.put(EngineEvent("error", str(error)))
                operation.state = "error"
            finally:
                if operation.state != "error":
                    operation.state = "cancelled" if operation.cancel_event.is_set() else "done"
                operation.events.put(EngineEvent("finished", operation.state))

        operation.thread = threading.Thread(target=worker, daemon=True)
        operation.thread.start()
        return operation

    def scan(self) -> Operation:
        return self.start_command("scan_networks", max_wait=45)

    def fs_list(self, relative: str = "") -> Operation:
        encoded = "-" if not relative else fs_path64(relative)
        return self.start_command(f"fs ls {encoded}", max_wait=20)

    def fs_remove(self, relative: str) -> Operation:
        return self.start_command(f"fs rm {fs_path64(relative)}", max_wait=20)

    def switch_baud(self, rate: int) -> Operation:
        allowed = {115200, 230400, 460800, 921600, 1000000, 1500000, 2000000, 3000000, 4000000}
        if rate not in allowed:
            raise ValueError("Unsupported JanOS UART baud rate")
        operation = Operation(f"uart_baud {rate}")
        if self._active and self._active.state == "running":
            raise RuntimeError("Another UART operation is already running")
        self._active = operation

        def worker() -> None:
            try:
                if self.demo:
                    self.baud_rate = rate
                    operation.events.put(EngineEvent("line", f"[SIMULATED] UART confirmed at {rate}"))
                    return
                with self._lock:
                    assert self.serial
                    self.serial.reset_input_buffer()
                    self._write_command(f"uart_baud {rate}")
                    lines = self._read_lines(2.5, 0.2, lambda line: operation.events.put(EngineEvent("line", line)))
                    if not any("[UARTB] switching" in line for line in lines):
                        raise RuntimeError("Board rejected UART baud switch")
                    self.serial.baudrate = rate
                    self.baud_rate = rate
                    time.sleep(0.1)
                    self._write_command("uart_baud_confirm")
                    lines = self._read_lines(3, 0.4, lambda line: operation.events.put(EngineEvent("line", line)))
                    if not any("[UARTB] confirmed" in line for line in lines):
                        time.sleep(10.2)
                        self.serial.baudrate = 115200
                        self.baud_rate = 115200
                        raise RuntimeError("Baud confirmation failed; host returned to 115200")
            except Exception as error:
                operation.state = "error"
                operation.events.put(EngineEvent("error", str(error)))
            finally:
                if operation.state != "error":
                    operation.state = "done"
                operation.events.put(EngineEvent("finished", operation.state))

        operation.thread = threading.Thread(target=worker, daemon=True)
        operation.thread.start()
        return operation

    def _read_exact(self, size: int, timeout: float) -> bytes:
        assert self.serial
        deadline = time.monotonic() + timeout
        data = bytearray()
        while len(data) < size and time.monotonic() < deadline:
            chunk = self.serial.read(size - len(data))
            if chunk:
                data.extend(chunk)
        if len(data) != size:
            raise TimeoutError(f"UART timeout {len(data)}/{size}")
        return bytes(data)

    def download(self, remote: str, local_name: str = "", *, legacy: bool = False) -> Operation:
        destination = self.data_dir / "downloads" / (local_name or Path(remote).name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        operation = Operation(f"fs get {remote}")
        if self._active and self._active.state == "running":
            raise RuntimeError("Another UART operation is already running")
        self._active = operation

        def worker() -> None:
            part = destination.with_suffix(destination.suffix + ".part")
            try:
                if self.demo:
                    part.write_bytes(b"SIMULATED\n")
                    part.replace(destination)
                    operation.events.put(EngineEvent("line", f"[SIMULATED] saved {destination}"))
                    return
                with self._lock:
                    assert self.serial
                    self.serial.reset_input_buffer()
                    self._write_command(f'send_file "{remote}"' if legacy else f"fs get {fs_path64(remote)}")
                    begin = ""
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        line = self.serial.readline().decode("utf-8", errors="replace").strip()
                        if "[FT] begin" in line:
                            begin = line
                        if line == "[FT] END" and begin:
                            break
                        if "ERROR" in line or " error " in line.lower():
                            raise RuntimeError(line)
                    fields = dict(re.findall(r"(size|bsize|ack_ms)=([0-9]+)", begin))
                    total = int(fields["size"])
                    block_size = int(fields["bsize"])
                    timeout = max(8, int(fields.get("ack_ms", "8000")) / 1000)
                    received = index = 0
                    crc = 0
                    with part.open("wb") as output:
                        while received < total:
                            frame = self._read_exact(16, timeout)
                            frame_index, length, expected_crc = parse_ftb_header(frame)
                            if frame_index != index or length > block_size:
                                self.serial.write(b"\x18")
                                raise RuntimeError("Invalid FTB/1 sequence")
                            payload = self._read_exact(length, timeout)
                            if zlib.crc32(payload) & 0xFFFFFFFF != expected_crc:
                                self.serial.write(b"\x15")
                                continue
                            output.write(payload)
                            crc = zlib.crc32(payload, crc)
                            received += length
                            index += 1
                            self.serial.write(b"\x06")
                            self.serial.flush()
                            operation.events.put(EngineEvent("progress", f"{received}/{total}"))
                    terminal = self._read_lines(10, 1, lambda line: operation.events.put(EngineEvent("line", line)))
                    done = next((line for line in terminal if "[FT] done" in line), "")
                    match = re.search(r"crc32=([0-9a-fA-F]{8})", done)
                    if match and int(match.group(1), 16) != crc & 0xFFFFFFFF:
                        raise RuntimeError("Whole-file CRC mismatch")
                    part.replace(destination)
                    operation.events.put(EngineEvent("saved", str(destination), destination))
            except Exception as error:
                operation.state = "error"
                operation.events.put(EngineEvent("error", str(error)))
            finally:
                if operation.state != "error":
                    operation.state = "done"
                operation.events.put(EngineEvent("finished", operation.state))

        operation.thread = threading.Thread(target=worker, daemon=True)
        operation.thread.start()
        return operation

    def upload(self, local: str, remote: str, *, replace: bool = False) -> Operation:
        source = Path(local).expanduser()
        operation = Operation(f"fs put {remote}")
        if self._active and self._active.state == "running":
            raise RuntimeError("Another UART operation is already running")
        self._active = operation

        def worker() -> None:
            try:
                data = source.read_bytes()
                file_crc = zlib.crc32(data) & 0xFFFFFFFF
                if self.demo:
                    operation.events.put(EngineEvent("line", f"[SIMULATED] uploaded {len(data)} bytes"))
                    return
                with self._lock:
                    assert self.serial
                    command = f"fs put {fs_path64(remote)} {len(data)} {file_crc:08X}" + (" replace" if replace else "")
                    self.serial.reset_input_buffer()
                    self._write_command(command)
                    ready = ""
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        line = self.serial.readline().decode("utf-8", errors="replace").strip()
                        if "[FS/1] READY" in line:
                            ready = line
                        if line == "[FS/1] END":
                            break
                        if "ERROR" in line:
                            raise RuntimeError(line)
                    fields = dict(re.findall(r"(bsize|rx_ms)=([0-9]+)", ready))
                    block_size = int(fields.get("bsize", "1024"))
                    timeout = max(8, int(fields.get("rx_ms", "8000")) / 1000 + 2)
                    offset = index = 0
                    while offset < len(data):
                        payload = data[offset:offset + block_size]
                        self.serial.write(make_ftb_frame(index, payload))
                        self.serial.flush()
                        offset += len(payload)
                        validate_fta_frame(self._read_exact(32, timeout), index, offset)
                        index += 1
                        operation.events.put(EngineEvent("progress", f"{offset}/{len(data)}"))
                    self.serial.write(make_ftb_finish(index))
                    self.serial.flush()
                    validate_fta_frame(self._read_exact(32, timeout), index, len(data))
                    self.serial.write(b"\x18")
                    self.serial.flush()
                    terminal = self._read_lines(10, 1, lambda line: operation.events.put(EngineEvent("line", line)))
                    if not any("[FS/1] DONE" in line for line in terminal):
                        raise RuntimeError("Upload finished without FS/1 DONE")
            except Exception as error:
                operation.state = "error"
                operation.events.put(EngineEvent("error", str(error)))
            finally:
                if operation.state != "error":
                    operation.state = "done"
                operation.events.put(EngineEvent("finished", operation.state))

        operation.thread = threading.Thread(target=worker, daemon=True)
        operation.thread.start()
        return operation

