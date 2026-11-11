"""Keyboard-first state machine for the Cardputer Zero JanOS frontend."""

from __future__ import annotations

import queue
import threading
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from janos_core import NetworkRecord, parse_network_line

from .engine import CatalogEntry, EngineEvent, JanOSEngine, Operation


HOME = ("Connect / board", "Wi-Fi scan", "Functions", "SD files", "Raw console", "Settings", "Exit")
FILES = ("List directory", "Download file", "Upload file", "Delete file", "Legacy send_file", "FS capabilities", "Crack worker files", "Back")
CRACK = (
    "Upload wordlist", "Upload HCCAPX capture", "Capabilities", "Probe cache",
    "Start shard", "Status", "Cancel job", "Diagnostics", "Reset partial", "Raw arguments", "Back",
)
SETTINGS = ("Probe capabilities", "Refresh ports", "UART baud", "Bright accents", "About", "Back")


@dataclass
class ViewState:
    screen: str = "splash"
    title: str = "JanOS Controller"
    rows: list[str] = field(default_factory=list)
    selected: int = 0
    scroll: int = 0
    hint: str = "ENTER continue"
    status: str = ""
    accent: str = "cyan"
    connected: bool = False
    firmware_version: str = ""
    simulated: bool = False
    input_text: str = ""
    editing: bool = False


class Controller:
    def __init__(self, device: str | None = None, demo: bool = False) -> None:
        self.engine = JanOSEngine(demo=demo)
        self.screen = "splash"
        self.selected = 0
        self.scroll = 0
        self.logs: list[str] = []
        self.error = ""
        self.operation: Operation | None = None
        self.networks: list[NetworkRecord] = []
        self.selected_networks: set[str] = set()
        self.category = ""
        self.command: CatalogEntry | None = None
        self.input_text = ""
        self.form_kind = ""
        self.form_labels: list[str] = []
        self.form_values: list[str] = []
        self.form_index = 0
        self.pending_confirm: tuple[CatalogEntry, str] | None = None
        self.ports_cache = self.engine.ports()
        self.theme_bright = False
        self.quit_requested = False
        self.dirty = True
        self._background: queue.Queue[tuple[str, object]] = queue.Queue()
        if demo:
            self.engine.connect(device or self.ports_cache[0])
        elif device:
            self._connect_async(device)

    @staticmethod
    def _wrap(lines: list[str], width: int = 49) -> list[str]:
        return [piece for line in lines for piece in (textwrap.wrap(str(line), width) or [""])]

    def _goto(self, screen: str, *, selected: int = 0) -> None:
        self.screen = screen
        self.selected = selected
        self.scroll = 0
        self.input_text = ""
        self.dirty = True

    def _connect_async(self, device: str) -> None:
        self.logs = [f"Opening {device}"]
        self._goto("connecting")

        def worker() -> None:
            try:
                self.engine.connect(device)
                self.engine.probe()
                self._background.put(("connected", device))
            except Exception as error:
                self._background.put(("error", str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def _probe_async(self) -> None:
        self.logs = ["Reading version and command registry..."]
        self._goto("connecting")

        def worker() -> None:
            try:
                self.engine.probe()
                self._background.put(("probed", self.engine.firmware_version))
            except Exception as error:
                self._background.put(("error", str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def categories(self) -> list[str]:
        preferred = [
            "Wi-Fi tools", "WPS and Bluetooth", "Portals and gateways",
            "Zigbee / 802.15.4", "Wardrive services", "Handshake and cracking",
            "OTA and firmware", "Hardware and diagnostics", "SD / binary transfer",
            "Python workflows",
        ]
        present = {entry.group for entry in self.engine.catalog}
        return [item for item in preferred if item in present] + sorted(present - set(preferred))

    def commands(self) -> list[CatalogEntry]:
        seen = set()
        output = []
        for entry in self.engine.catalog:
            if entry.group == self.category and entry.command not in seen:
                seen.add(entry.command)
                output.append(entry)
        return output

    def view(self) -> ViewState:
        common = dict(
            selected=self.selected,
            scroll=self.scroll,
            connected=self.engine.connected,
            firmware_version=self.engine.firmware_version,
            simulated=self.engine.demo,
        )
        if self.screen == "splash":
            return ViewState(screen="splash", rows=["LAB5 / D3h420"], **common)
        if self.screen == "home":
            return ViewState(screen="menu", title="JANOS / HOME", rows=list(HOME), hint="F/X move  ENTER select", **common)
        if self.screen == "ports":
            rows = self.ports_cache or ["No serial ports — R refresh"]
            return ViewState(screen="list", title="MONSTER UART", rows=rows, hint="ENTER connect  R refresh  ESC back", **common)
        if self.screen == "categories":
            return ViewState(screen="list", title="FUNCTION GROUPS", rows=self.categories(), hint="ENTER open  ESC back", **common)
        if self.screen == "commands":
            rows = []
            for entry in self.commands():
                available = not self.engine.available_commands or entry.command in self.engine.available_commands
                rows.append(("  " if available else "! ") + entry.label)
            return ViewState(screen="list", title=self.category.upper(), rows=rows, hint="! not reported  ENTER open", **common)
        if self.screen == "command":
            assert self.command
            available = not self.engine.available_commands or self.command.command in self.engine.available_commands
            rows = [
                self.command.label,
                f"Command: {self.command.command}",
                f"Arguments: {self.command.arguments or '(none)'}",
                f"Mode: {'stream' if self.command.stream else 'one-shot'}",
                f"Board: {'available' if available else 'not reported by help'}",
            ]
            return ViewState(screen="detail", title="COMMAND", rows=self._wrap(rows), hint="ENTER run  ESC back", accent="green" if available else "amber", **common)
        if self.screen == "input":
            label = self.form_labels[self.form_index] if self.form_labels else "Arguments"
            rows = [label, self.input_text + "_", f"Field {self.form_index + 1}/{max(1, len(self.form_labels))}"]
            return ViewState(screen="detail", title=self.form_kind.upper(), rows=rows, input_text=self.input_text, editing=True, hint="ENTER next  ESC cancel", **common)
        if self.screen == "confirm":
            assert self.pending_confirm
            entry, suffix = self.pending_confirm
            command = f"{entry.command} {suffix}".strip()
            return ViewState(screen="detail", title="CONFIRM", rows=self._wrap(["Potentially disruptive command:", command]), hint="ENTER confirm  ESC cancel", accent="amber", **common)
        if self.screen == "scan_results":
            rows = []
            for record in self.networks:
                mark = "*" if record.index in self.selected_networks else " "
                rows.append(f"{mark}{record.index} {record.ssid or '<hidden>'} {record.rssi}dBm ch{record.channel}")
            return ViewState(screen="list", title="WI-FI SCAN", rows=rows or ["No networks"], hint="ENTER select  RIGHT inspect  ESC back", **common)
        if self.screen == "files":
            return ViewState(screen="list", title="SD / FS/1", rows=list(FILES), hint="ENTER select  ESC back", **common)
        if self.screen == "crack":
            return ViewState(screen="list", title="CRACK WORKER", rows=list(CRACK), hint="ENTER select  ESC back", **common)
        if self.screen == "settings":
            rows = list(SETTINGS)
            rows[3] = f"Bright accents  {'ON' if self.theme_bright else 'OFF'}"
            return ViewState(screen="list", title="SETTINGS", rows=rows, hint="ENTER select  ESC back", **common)
        if self.screen == "about":
            rows = self._wrap([
                "JanOS Controller / Cardputer Zero",
                "Native ARM64 APPLaunch frontend",
                "Shared Python command and protocol core",
                f"Catalog: {len({entry.command for entry in self.engine.catalog})} commands",
                f"State: {self.engine.data_dir}",
            ])
            return ViewState(screen="detail", title="ABOUT", rows=rows, hint="ESC back", **common)
        if self.screen == "error":
            return ViewState(screen="detail", title="ERROR", rows=self._wrap([self.error]), hint="ESC back  HOME menu", accent="red", **common)
        title = "CONNECTING" if self.screen == "connecting" else (self.command.label.upper() if self.command else "UART OUTPUT")
        hint = "ESC cancel  HOME menu" if self.operation and self.operation.state == "running" else "ESC back  HOME menu"
        return ViewState(screen="log", title=title, rows=self._wrap(self.logs[-400:]), hint=hint, status=self.operation.state if self.operation else "", **common)

    def tick(self) -> bool:
        changed = self.dirty
        self.dirty = False
        try:
            while True:
                kind, payload = self._background.get_nowait()
                if kind in {"connected", "probed"}:
                    self.logs.append(f"Connected: {self.engine.device}")
                    self.logs.append(f"JanOS: {self.engine.firmware_version}")
                    self.logs.append(f"Commands: {len(self.engine.available_commands) or 'unknown'}")
                    self._goto("home")
                else:
                    self.error = str(payload)
                    self._goto("error")
                changed = True
        except queue.Empty:
            pass
        if self.operation:
            for event in self.operation.poll():
                if event.kind in {"line", "progress", "saved"}:
                    self.logs.append(event.message)
                    self.logs = self.logs[-500:]
                    if event.kind == "line" and self.operation.command == "scan_networks":
                        record = parse_network_line(event.message)
                        if record and all(item.index != record.index for item in self.networks):
                            self.networks.append(record)
                elif event.kind == "error":
                    self.error = event.message
                    self._goto("error")
                elif event.kind == "finished":
                    if self.operation.command == "scan_networks" and self.screen == "log":
                        self._goto("scan_results")
                    self.dirty = True
                changed = True
        return changed or self.dirty

    def _start_operation(self, operation: Operation, title: str = "") -> None:
        self.operation = operation
        self.logs = [f"UART -> {operation.command}"]
        self._goto("log")

    def _execute(self, entry: CatalogEntry, suffix: str) -> None:
        command = f"{entry.command} {suffix}".strip()
        action = suffix.split(maxsplit=1)[0].lower() if suffix.strip() else ""
        continuous_commands = {
            "channel_view", "packet_monitor", "deauth_detector",
            "subghz_freq_analyzer", "subghz_jam", "subghz_rx",
            "subghz_scanner", "subghz_tpms", "subghz_weather",
        }
        continuous = entry.command.startswith("start_") or entry.command in continuous_commands or (
            entry.command in {"wps", "jwps", "capture_gateway"}
            and action == "start"
        )
        self._start_operation(self.engine.start_command(command, stream=continuous))

    def _start_form(self, kind: str, labels: list[str]) -> None:
        self.form_kind = kind
        self.form_labels = labels
        self.form_values = [""] * len(labels)
        self.form_index = 0
        self.input_text = ""
        self._goto("input")

    def _finish_form(self) -> None:
        values = list(self.form_values)
        kind = self.form_kind
        try:
            if kind == "arguments":
                assert self.command
                suffix = values[0].strip()
                unsupported = bool(
                    self.engine.available_commands
                    and self.command.command not in self.engine.available_commands
                )
                if self.command.confirm or unsupported:
                    self.pending_confirm = (self.command, suffix)
                    self._goto("confirm")
                else:
                    self._execute(self.command, suffix)
            elif kind == "raw command":
                command = values[0].strip()
                if command:
                    self._start_operation(self.engine.start_command(command, stream=False))
            elif kind == "list directory":
                self._start_operation(self.engine.fs_list(values[0].strip()))
            elif kind == "download file":
                self._start_operation(self.engine.download(values[0].strip(), values[1].strip()))
            elif kind == "upload file":
                self._start_operation(self.engine.upload(values[0].strip(), values[1].strip(), replace=True))
            elif kind == "delete file":
                self._start_operation(self.engine.fs_remove(values[0].strip()))
            elif kind == "legacy send_file":
                self._start_operation(self.engine.download(values[0].strip(), values[1].strip(), legacy=True))
            elif kind == "uart baud":
                self._start_operation(self.engine.switch_baud(int(values[0].strip())))
            elif kind in {"crack upload wordlist", "crack upload capture"}:
                data_kind = "wordlist" if kind.endswith("wordlist") else "capture"
                self._start_operation(self.engine.crack_upload(values[0].strip(), data_kind))
            elif kind in {"crack probe", "crack reset"}:
                action = "probe" if kind.endswith("probe") else "reset"
                data_kind, size, checksum = (value.strip() for value in values)
                self._start_operation(
                    self.engine.start_command(
                        f"crack_worker {action} {data_kind} {size} {checksum}", max_wait=15
                    )
                )
            elif kind == "crack start":
                suffix = " ".join(value.strip() for value in values)
                self._start_operation(
                    self.engine.start_command(f"crack_worker start {suffix}", max_wait=20)
                )
            elif kind == "crack cancel":
                job = values[0].strip()
                self._start_operation(
                    self.engine.start_command(f"crack_worker cancel {job}".strip(), max_wait=10)
                )
            elif kind == "crack raw":
                suffix = values[0].strip()
                if suffix:
                    self._start_operation(self.engine.start_command(f"crack_worker {suffix}", max_wait=120))
        except Exception as error:
            self.error = str(error)
            self._goto("error")

    def handle(self, key: str, char: str = "") -> None:
        if self.quit_requested:
            return
        if self.screen == "splash":
            self._goto("home")
            return
        if key == "HOME":
            if self.operation and self.operation.state == "running":
                self.operation.cancel()
            self._goto("home")
            return
        if self.screen == "input":
            if key == "ESC":
                target = {
                    "arguments": "command",
                    "raw command": "home",
                    "uart baud": "settings",
                    "crack upload wordlist": "crack",
                    "crack upload capture": "crack",
                    "crack probe": "crack",
                    "crack reset": "crack",
                    "crack start": "crack",
                    "crack cancel": "crack",
                    "crack raw": "crack",
                }.get(self.form_kind, "files")
                self._goto(target)
            elif key == "BACKSPACE":
                self.input_text = self.input_text[:-1]
            elif key == "TEXT" and char and len(self.input_text) < 2048:
                self.input_text += char
            elif key == "ENTER":
                self.form_values[self.form_index] = self.input_text
                if self.form_index + 1 < len(self.form_labels):
                    self.form_index += 1
                    self.input_text = self.form_values[self.form_index]
                else:
                    self._finish_form()
            self.dirty = True
            return
        if self.screen == "confirm":
            if key == "ENTER" and self.pending_confirm:
                entry, suffix = self.pending_confirm
                self.pending_confirm = None
                self._execute(entry, suffix)
            elif key == "ESC":
                self.pending_confirm = None
                self._goto("command")
            return
        if key == "ESC":
            if self.operation and self.operation.state == "running" and self.screen == "log":
                self.operation.cancel()
                self.dirty = True
                return
            back = {
                "home": "exit", "ports": "home", "categories": "home", "commands": "categories",
                "command": "commands", "scan_results": "home", "files": "home", "settings": "home",
                "crack": "files",
                "about": "settings", "error": "home", "log": "home", "connecting": "home",
            }
            target = back.get(self.screen, "home")
            if target == "exit":
                self.quit_requested = True
            else:
                self._goto(target)
            return
        rows = self.view().rows
        if key in {"UP", "DOWN", "PAGEUP", "PAGEDOWN"}:
            step = {"UP": -1, "DOWN": 1, "PAGEUP": -5, "PAGEDOWN": 5}[key]
            if self.screen in {"log", "about", "error", "command", "connecting"}:
                self.scroll = max(0, min(max(0, len(rows) - 7), self.scroll + step))
            elif rows:
                self.selected = max(0, min(len(rows) - 1, self.selected + step))
            self.dirty = True
            return
        if self.screen == "home" and key == "ENTER":
            item = HOME[self.selected]
            if item == "Connect / board":
                self.ports_cache = self.engine.ports()
                self._goto("ports")
            elif item == "Wi-Fi scan":
                if not self.engine.connected:
                    self.error = "Connect MonsterC5 first"
                    self._goto("error")
                else:
                    self.networks.clear()
                    self._start_operation(self.engine.scan())
            elif item == "Functions": self._goto("categories")
            elif item == "SD files": self._goto("files")
            elif item == "Raw console": self._start_form("raw command", ["JanOS command"])
            elif item == "Settings": self._goto("settings")
            else: self.quit_requested = True
            return
        if self.screen == "ports":
            if key == "TEXT" and char.lower() == "r":
                self.ports_cache = self.engine.ports(); self.selected = 0; self.dirty = True
            elif key == "ENTER" and self.ports_cache:
                self._connect_async(self.ports_cache[self.selected])
            return
        if self.screen == "categories" and key == "ENTER":
            categories = self.categories()
            if categories:
                self.category = categories[self.selected]
                self._goto("commands")
            return
        if self.screen == "commands" and key == "ENTER":
            commands = self.commands()
            if commands:
                self.command = commands[self.selected]
                self._goto("command")
            return
        if self.screen == "command" and key == "ENTER" and self.command:
            if not self.engine.connected:
                self.error = "Connect MonsterC5 first"; self._goto("error")
            elif self.command.command == "send_file":
                self._start_form("legacy send_file", ["Absolute remote path", "Local filename (blank = same)"])
            elif self.command.command == "uart_baud":
                self._start_form("uart baud", ["115200..4000000"])
            elif self.command.command == "fs":
                self._goto("files")
            elif self.command.command == "crack_worker":
                self._goto("crack")
            elif self.command.arguments:
                self._start_form("arguments", [self.command.arguments])
            elif self.command.confirm or (
                self.engine.available_commands
                and self.command.command not in self.engine.available_commands
            ):
                self.pending_confirm = (self.command, ""); self._goto("confirm")
            else:
                self._execute(self.command, "")
            return
        if self.screen == "scan_results" and self.networks:
            record = self.networks[min(self.selected, len(self.networks) - 1)]
            if key == "ENTER":
                self.selected_networks = {record.index}
                self._start_operation(self.engine.start_command(f"select_networks {record.index}"))
            elif key == "RIGHT":
                self._start_operation(self.engine.start_command(f"inspect_network {record.index}"))
            return
        if self.screen == "files" and key == "ENTER":
            item = FILES[self.selected]
            if item == "List directory": self._start_form("list directory", ["Relative directory (blank = root)"])
            elif item == "Download file": self._start_form("download file", ["Remote relative path", "Local filename (blank = same)"])
            elif item == "Upload file": self._start_form("upload file", ["Local absolute path", "Remote relative path"])
            elif item == "Delete file": self._start_form("delete file", ["Remote relative path"])
            elif item == "Legacy send_file": self._start_form("legacy send_file", ["Absolute remote path", "Local filename (blank = same)"])
            elif item == "FS capabilities": self._start_operation(self.engine.start_command("fs hello"))
            elif item == "Crack worker files": self._goto("crack")
            else: self._goto("home")
            return
        if self.screen == "crack" and key == "ENTER":
            item = CRACK[self.selected]
            if item == "Upload wordlist":
                self._start_form("crack upload wordlist", ["File in uploads/ or absolute path"])
            elif item == "Upload HCCAPX capture":
                self._start_form("crack upload capture", ["HCCAPX in uploads/ or absolute path"])
            elif item == "Capabilities":
                self._start_operation(self.engine.start_command("crack_worker capabilities", max_wait=10))
            elif item == "Probe cache":
                self._start_form("crack probe", ["wordlist or capture", "Size in bytes", "CRC32 hex"])
            elif item == "Start shard":
                self._start_form("crack start", [
                    "Job ID", "Capture size", "Capture CRC32", "Wordlist size",
                    "Wordlist CRC32", "Start byte", "End byte (0 = EOF)",
                ])
            elif item == "Status":
                self._start_operation(self.engine.start_command("crack_worker status", max_wait=10))
            elif item == "Cancel job":
                self._start_form("crack cancel", ["Job ID (blank = current)"])
            elif item == "Diagnostics":
                self._start_operation(self.engine.start_command("crack_worker diag", max_wait=10))
            elif item == "Reset partial":
                self._start_form("crack reset", ["wordlist or capture", "Size in bytes", "CRC32 hex"])
            elif item == "Raw arguments":
                self._start_form("crack raw", ["Arguments after crack_worker"])
            else:
                self._goto("files")
            return
        if self.screen == "settings" and key == "ENTER":
            item = SETTINGS[self.selected]
            if item == "Probe capabilities": self._probe_async()
            elif item == "Refresh ports": self.ports_cache = self.engine.ports(); self.dirty = True
            elif item == "UART baud": self._start_form("uart baud", ["115200..4000000"])
            elif item == "Bright accents": self.theme_bright = not self.theme_bright; self.dirty = True
            elif item == "About": self._goto("about")
            else: self._goto("home")

    def close(self) -> None:
        if self.operation and self.operation.state == "running":
            self.operation.cancel()
            if self.operation.thread:
                self.operation.thread.join(timeout=3)
        self.engine.close()

