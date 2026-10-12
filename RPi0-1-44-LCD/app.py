#!/usr/bin/env python3
"""Joystick JanOS frontend for the Seengreat 128x128 ST7735S HAT.

The existing JanOS_app.py remains the full terminal frontend.  This frontend
speaks the same USB UART protocol and is deliberately independent of a TTY.
"""

from __future__ import annotations

import argparse
from collections import deque
import math
from pathlib import Path
import re
import signal
import time
from typing import Callable

from hardware import DEFAULT_ROTATION
from protocol import JanOSLink, parse_network_line

SIZE = 128
SPLASH_IMAGE = Path(__file__).with_name("splash.png")
DEFAULT_SPLASH_SECONDS = 3.0
BG = (7, 13, 24)
PANEL = (15, 31, 48)
CYAN = (48, 216, 225)
WHITE = (235, 244, 250)
MUTED = (138, 164, 180)
GREEN = (58, 223, 151)
RED = (249, 94, 110)
YELLOW = (255, 204, 99)


def _font(size: int):
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


class JanOSUI:
    """Small state machine; display, buttons and serial link can be faked."""

    CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_-./:=,@+?!#\"'ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def __init__(self, display, buttons, link: JanOSLink,
                 now: Callable[[], float] = time.monotonic):
        self.display = display
        self.buttons = buttons
        self.link = link
        self.now = now
        self.font = _font(10)
        self.small_font = _font(8)
        self.title_font = _font(11)
        self.stack: list[tuple[str, int]] = [("home", 0)]
        self.view = "menu"
        self.title = "JanOS"
        self.logs: deque[str] = deque(maxlen=240)
        self.log_scroll = 0
        self.networks: dict[str, dict[str, str]] = {}
        self.selected: set[str] = set()
        self.signals: dict[str, dict[str, dict[str, str]]] = {"mem": {}, "sd": {}}
        self.current_network = ""
        self.current_signal: tuple[str, str] = ("mem", "")
        self.pending_scan: dict | None = None
        self.pending_signals: dict | None = None
        self.active_stop: str | None = None
        self.active_name = ""
        self.editor_text = ""
        self.editor_index = 0
        self.confirm_label = ""
        self.confirm_action: Callable[[], None] | None = None
        self.connected_before = False
        self.status_message = "Podlacz ESP32-C5"
        self.dirty = True
        self.last_render = 0.0

    def _items(self, menu: str) -> list[tuple[str, str]]:
        if menu == "home":
            return [("Wi-Fi", "menu:wifi"), ("Sniffer", "menu:sniffer"),
                    ("Akcje RF", "menu:actions"), ("Wardrive", "menu:wardrive"),
                    ("Bluetooth", "menu:bluetooth"), ("SubGHz", "menu:subghz"),
                    ("Karta SD", "menu:sd"), ("Urzadzenie", "menu:device"),
                    ("Komenda UART", "editor:"), ("Ostatnie logi", "log")]
        if menu == "wifi":
            return [("Skanuj sieci", "scan"), ("Lista sieci", "menu:networks"),
                    ("Wybrane AP", "selected"), ("Wyczysc wybor", "unselect"),
                    ("Wyniki skanu", "cmd:show_scan_results")]
        if menu == "networks":
            rows = sorted(self.networks.values(), key=lambda n: int(n["index"]) if n["index"].isdigit() else 9999)
            return [(f"{'*' if n['index'] in self.selected else ' '}#{n['index']} {n['ssid']}",
                     f"net:{n['index']}") for n in rows] or [("Brak sieci. Skanuj", "scan")]
        if menu == "network":
            n = self.networks.get(self.current_network, {})
            idx = self.current_network
            return [(f"SSID: {n.get('ssid', '?')}", "noop"),
                    (f"BSSID: {n.get('bssid', '?')}", "noop"),
                    (f"CH {n.get('channel', '?')}  {n.get('rssi', '?')} dBm", "noop"),
                    ("Odznacz" if idx in self.selected else "Zaznacz", f"toggle:{idx}"),
                    ("Sprawdz AP", f"cmd:inspect_network {idx}"),
                    ("Akcje dla AP", "menu:actions")]
        if menu == "sniffer":
            return [("Start sniffer", "live:stop:start_sniffer"),
                    ("Wyniki", "cmd:show_sniffer_results"),
                    ("Wyniki + vendor", "cmd:show_sniffer_results_vendor"),
                    ("Probe requests", "cmd:show_probes"),
                    ("Probes + vendor", "cmd:show_probes_vendor"),
                    ("Lista probes", "cmd:list_probes"),
                    ("Sniffer Dog", "live:stop:start_sniffer_dog"),
                    ("Deauth detector", "live:stop:deauth_detector"),
                    ("AP locator", "live:stop:start_ap_locator"),
                    ("Packet monitor", "editor:packet_monitor "),
                    ("Channel view", "live:stop:channel_view"),
                    ("Wyczysc wyniki", "confirm:clear_sniffer_results")]
        if menu == "actions":
            return [("Deauth wybrane", "target:start_deauth"),
                    ("SAE overflow", "target1:sae_overflow"),
                    ("Blackout", "confirm_live:start_blackout"),
                    ("Handshake", "confirm_live:start_handshake"),
                    ("Beacon spam", "menu:beacon"),
                    ("Portal", "menu:portal"),
                    ("Evil Twin", "menu:evil"),
                    ("ARP / MITM", "menu:inside"),
                    ("Stop wszystkich", "cmd:stop")]
        if menu == "beacon":
            return [("Lista SSID", "cmd:list_ssids"),
                    ("Dodaj SSID", "editor:add_ssid \""),
                    ("Usun nr SSID", "editor:remove_ssid "),
                    ("Start", "confirm_live:start_beacon_spam_ssids"),
                    ("Stop", "cmd:stop")]
        if menu == "portal":
            return [("Lista HTML", "cmd:list_sd"),
                    ("Wybierz HTML", "editor:select_html "),
                    ("Start z SSID", "editor:start_portal "),
                    ("Zebrane dane", "cmd:show_pass portal"),
                    ("Stop", "cmd:stop")]
        if menu == "evil":
            return [("Lista HTML", "cmd:list_sd"),
                    ("Wybierz HTML", "editor:select_html "),
                    ("Start wybrany AP", "target1:start_evil_twin"),
                    ("Zebrane dane", "cmd:show_pass evil"),
                    ("Stop", "cmd:stop")]
        if menu == "inside":
            return [("Polacz Wi-Fi STA", "editor:wifi_connect \""),
                    ("Lista hostow", "cmd:list_hosts"),
                    ("ARP ban MAC IP", "editor:arp_ban "),
                    ("PCAP net", "confirm_live:start_pcap net"),
                    ("Stop", "cmd:stop")]
        if menu == "wardrive":
            return [("Start wardrive", "live:stop:start_wardrive"),
                    ("Promisc", "live:stop:start_wardrive_promisc"),
                    ("Promisc + trace", "live:stop:start_wardrive_promisc_trace"),
                    ("GPS", "menu:gps"),
                    ("Konfig. wardrive", "cmd:get_wardrive_config"),
                    ("Pasma", "editor:set_wardrive_bands "),
                    ("Kanaly", "editor:set_wardrive_channels "),
                    ("RSSI delta", "editor:set_wardrive_rssi_delta "),
                    ("Blacklist", "cmd:wardrive_blacklist list")]
        if menu == "gps":
            return [("Modul obecny", "cmd:gps_set"),
                    ("Ustaw M5", "cmd:gps_set m5"),
                    ("Ustaw ATGM", "cmd:gps_set atgm"),
                    ("Ustaw Tab5", "cmd:gps_set tab5"),
                    ("Ustaw CAP", "cmd:gps_set cap"),
                    ("GPS raw", "live:stop:start_gps_raw")]
        if menu == "bluetooth":
            return [("Skan BLE", "cmd:scan_bt"),
                    ("AirTag/SmartTag", "live:stop:scan_airtag"),
                    ("Anti-surveillance", "live:stop:start_antisurveillance")]
        if menu == "subghz":
            return [("Status radia", "cmd:subghz_status"),
                    ("Odbior 433.92", "subrx"),
                    ("Find & capture", "live:subghz_stop:subghz_freq_analyzer -85 hunt single timeout=2000"),
                    ("Skan czestotl.", "live:subghz_stop:subghz_scanner"),
                    ("Weather", "live:subghz_stop:subghz_weather"),
                    ("TPMS", "live:subghz_stop:subghz_tpms"),
                    ("Pamiec sygnalow", "signals:mem"),
                    ("Sygnaly na SD", "signals:sd"),
                    ("Zapisz cala pam.", "confirm:subghz_save all"),
                    ("Czestotl. MHz", "editor:subghz_freq "),
                    ("Narz. radia", "menu:radio_tools"),
                    ("Stop radia", "cmd:subghz_stop")]
        if menu == "radio_tools":
            return [("Status", "cmd:subghz_status"),
                    ("Czestotliwosc", "cmd:subghz_freq"),
                    ("Ustaw MHz", "editor:subghz_freq "),
                    ("Korekta MHz", "editor:subghz_set_freq_correction "),
                    ("Jam biezaca freq.", "confirm_live:subghz_stop:subghz_jam"),
                    ("Wyczysc pamiec", "confirm:subghz_clear"),
                    ("Prot. radia", "cmd:subghz_protocols"),
                    ("Debug", "cmd:subghz_debug")]
        if menu.startswith("signals:"):
            source = menu.split(":", 1)[1]
            rows = self.signals[source].values()
            items = [(f"#{s['idx']} {s.get('name', s.get('type', '?'))}",
                      f"signal:{source}:{s['idx']}") for s in rows]
            items.append(("Odswiez", f"signals:{source}"))
            if source == "mem":
                items.append(("Zapisz wszystkie", "confirm:subghz_save all"))
            return items
        if menu == "signal":
            source, idx = self.current_signal
            sig = self.signals[source].get(idx, {})
            items = [(f"{sig.get('type', '?')} {sig.get('freq', '?')} MHz", "noop"),
                     ("Info", f"cmd:subghz_info {idx} {source}"),
                     ("Odtworz", f"confirm:subghz_tx {idx} {source}"),
                     ("Odtworz RAW", f"confirm:subghz_tx {idx} {source} raw")]
            if source == "mem":
                items.append(("Zapisz na SD", f"cmd:subghz_save {idx}"))
            else:
                items.append(("Zmien nazwe", f"editor:subghz_rename {idx} "))
                items.append(("Usun z SD", f"confirm:subghz_delete {idx}"))
            return items
        if menu == "sd":
            return [("Status SD", "cmd:sd_status"), ("Lista SD", "cmd:list_sd"),
                    ("HTML", "cmd:list_dir /sdcard/lab/htmls"),
                    ("Wardrive logs", "cmd:list_dir /sdcard/lab/wardrives"),
                    ("Handshakes", "cmd:list_dir /sdcard/lab/handshakes"),
                    ("PCAP", "cmd:list_dir /sdcard/lab/pcaps"),
                    ("SubGHz", "signals:sd")]
        if menu == "device":
            return [("Polaczenie", "status"), ("Wersja", "cmd:version"),
                    ("Board name", "cmd:board_name"), ("Pomoc firmware", "cmd:help"),
                    ("Ping", "editor:ping "),
                    ("Vendor lookup", "cmd:vendor read"),
                    ("LED", "cmd:led read"), ("Wyswietlacz", "cmd:display read"),
                    ("Channel time", "cmd:channel_time read min"),
                    ("Restart ESP32", "confirm:reboot")]
        if menu == "editor_actions":
            return [("Wyslij", "editor_send"), ("Spacja", "editor_space"),
                    ("Usun znak", "editor_delete"), ("Wyczysc", "editor_clear"),
                    ("Wroc do liter", "editor_return"), ("Anuluj", "editor_cancel")]
        return []

    def _menu(self) -> str:
        return self.stack[-1][0]

    def _push(self, menu: str):
        self.stack.append((menu, 0))
        self.view = "menu"
        self.dirty = True

    def _pop(self):
        if len(self.stack) > 1:
            self.stack.pop()
        self.view = "menu"
        self.dirty = True

    def _command(self, command: str, *, live_stop: str | None = None):
        if self.active_stop:
            self.link.send(self.active_stop)
            self.logs.append(f"> {self.active_stop}")
            self.active_stop = None
        self.logs.append("> wifi_connect [ukryte dane]" if command.startswith("wifi_connect ")
                         else f"> {command}")
        if not self.link.send(command):
            self.status_message = self.link.error or "Brak polaczenia"
            self.logs.append(self.status_message)
        elif live_stop:
            self.active_stop = live_stop
            self.active_name = command
        self.title = command.split()[0]
        self.view = "log"
        self.log_scroll = 0
        self.dirty = True

    def _confirm(self, label: str, action: Callable[[], None]):
        self.confirm_label = label
        self.confirm_action = action
        self.view = "confirm"
        self.dirty = True

    def _do(self, action: str):
        if action == "noop":
            return
        if action.startswith("menu:"):
            self._push(action[5:])
        elif action == "scan":
            if not self.link.connected:
                self.status_message = "Brak ESP32-C5"
                self.dirty = True
                return
            self.link.send("unselect_networks")
            self.selected.clear()
            self.networks.clear()
            if self.link.send("scan_networks"):
                self.pending_scan = {"deadline": self.now() + 30, "phase": "direct", "last": self.now()}
                self.view = "scan"
                self.dirty = True
        elif action.startswith("net:"):
            self.current_network = action[4:]
            self._push("network")
        elif action.startswith("toggle:"):
            idx = action[7:]
            if idx in self.selected:
                self.selected.remove(idx)
            else:
                self.selected.add(idx)
            self.link.send("unselect_networks")
            if self.selected:
                self.link.send("select_networks " + " ".join(sorted(self.selected, key=int)))
            self.dirty = True
        elif action == "unselect":
            self.selected.clear()
            self._command("unselect_networks")
        elif action == "selected":
            self.status_message = "AP: " + (", ".join(sorted(self.selected, key=int)) or "brak")
            self.view = "status"
            self.dirty = True
        elif action.startswith("target1:") or action.startswith("target:"):
            exactly_one = action.startswith("target1:")
            command = action.split(":", 1)[1]
            if (len(self.selected) != 1 if exactly_one else not self.selected):
                self.status_message = "Wybierz 1 AP" if exactly_one else "Wybierz AP"
                self.view = "status"
                self.dirty = True
            else:
                self._confirm(command, lambda c=command: self._command(c, live_stop="stop"))
        elif action.startswith("confirm_live:"):
            payload = action.split(":", 1)[1]
            stop, command = payload.split(":", 1) if ":" in payload else ("stop", payload)
            self._confirm(command, lambda c=command, s=stop: self._command(c, live_stop=s))
        elif action.startswith("confirm:"):
            command = action.split(":", 1)[1]
            self._confirm(command, lambda c=command: self._command(c))
        elif action.startswith("live:"):
            _, stop, command = action.split(":", 2)
            self._command(command, live_stop=stop)
        elif action.startswith("cmd:"):
            self._command(action[4:])
        elif action == "subrx":
            if self.link.connected:
                self.link.send("subghz_stop")
                self.link.send("subghz_freq 433.92")
            self._command("subghz_rx rssi=-80", live_stop="subghz_stop")
        elif action.startswith("signals:"):
            source = action.split(":", 1)[1]
            if self.link.send(f"subghz_list {source}"):
                self.signals[source] = {}
                self.pending_signals = {"source": source, "deadline": self.now() + 8}
                self.view = "loading"
                self.title = f"Sygnaly {source}"
                self.dirty = True
            else:
                self.status_message = self.link.error or "Brak polaczenia"
                self.view = "status"
                self.dirty = True
        elif action.startswith("signal:"):
            _, source, idx = action.split(":", 2)
            self.current_signal = (source, idx)
            self._push("signal")
        elif action.startswith("editor:"):
            self.editor_text = action[7:]
            self.editor_index = 0
            self.view = "editor"
            self.dirty = True
        elif action == "editor_send":
            command = self.editor_text.strip()
            self._pop()
            if command:
                self._command(command)
        elif action == "editor_space":
            self.editor_text += " "
            self._pop()
            self.view = "editor"
        elif action == "editor_delete":
            self.editor_text = self.editor_text[:-1]
            self._pop()
            self.view = "editor"
        elif action == "editor_clear":
            self.editor_text = ""
            self._pop()
            self.view = "editor"
        elif action == "editor_return":
            self._pop()
            self.view = "editor"
        elif action == "editor_cancel":
            self._pop()
            self.view = "menu"
        elif action == "log":
            self.title = "Log UART"
            self.view = "log"
            self.log_scroll = 0
            self.dirty = True
        elif action == "status":
            self.view = "status"
            self.dirty = True

    def button(self, event: str):
        if event not in ("up", "down", "select", "back"):
            return
        if self.view == "menu":
            menu, selected = self.stack[-1]
            items = self._items(menu)
            if event == "back":
                self._pop()
                if menu == "editor_actions":
                    self.view = "editor"
            elif event in ("up", "down") and items:
                selected = (selected + (-1 if event == "up" else 1)) % len(items)
                self.stack[-1] = (menu, selected)
                self.dirty = True
            elif event == "select" and items:
                self._do(items[selected][1])
        elif self.view == "editor":
            if event == "up":
                self.editor_index = (self.editor_index - 1) % len(self.CHARS)
            elif event == "down":
                self.editor_index = (self.editor_index + 1) % len(self.CHARS)
            elif event == "select":
                self.editor_text += self.CHARS[self.editor_index]
            else:
                self._push("editor_actions")
            self.dirty = True
        elif self.view == "confirm":
            if event not in ("select", "back"):
                return
            action = self.confirm_action
            self.confirm_action = None
            self.view = "menu"
            if event == "select" and action:
                action()
            self.dirty = True
        elif self.view == "log":
            if event == "back":
                if self.active_stop:
                    self.link.send(self.active_stop)
                    self.logs.append(f"> {self.active_stop}")
                    self.active_stop = None
                self.view = "menu"
            elif event == "up":
                self.log_scroll += 1
            elif event == "down":
                self.log_scroll = max(0, self.log_scroll - 1)
            elif event == "select":
                self.log_scroll = 0
            self.dirty = True
        elif self.view in ("status", "loading", "scan") and event == "back":
            if self.view == "scan":
                self.link.send("stop")
                self.pending_scan = None
            if self.view == "loading":
                self.pending_signals = None
            self.view = "menu"
            self.dirty = True

    def _handle_line(self, line: str):
        line = line.strip()
        if not line:
            return
        public_line = "wifi_connect [ukryte dane]" if line.lower().lstrip("> ").startswith("wifi_connect ") else line
        self.logs.append(public_line)
        self.dirty = True
        if self.pending_scan:
            network = parse_network_line(line)
            if network and network["index"].isdigit():
                self.networks[network["index"]] = network
                self.pending_scan["last"] = self.now()
            if "Scan results printed" in line and self.pending_scan["phase"] == "direct":
                self._finish_scan()
        if self.pending_signals:
            source = self.pending_signals["source"]
            if line.startswith("[SUBGHZ_LIST] "):
                fields = dict(re.findall(r"(\w+)=([^\s]+)", line))
                idx = fields.get("idx", "")
                if idx.isdigit():
                    self.signals[source][idx] = fields
            elif line.startswith("[SUBGHZ_LIST_END]"):
                self._finish_signals()

    def _finish_scan(self):
        self.pending_scan = None
        self.status_message = f"Sieci: {len(self.networks)}"
        if self._menu() != "networks":
            self._push("networks")
        else:
            self.view = "menu"
        self.dirty = True

    def _finish_signals(self):
        source = self.pending_signals["source"] if self.pending_signals else "mem"
        self.pending_signals = None
        if self._menu() != f"signals:{source}":
            self._push(f"signals:{source}")
        else:
            self.view = "menu"
        self.dirty = True

    def tick(self):
        lines = self.link.poll()
        connected = self.link.connected
        if connected != self.connected_before:
            self.connected_before = connected
            if connected:
                self.status_message = "ESP32 polaczony"
                self.logs.append(f"Polaczono: {self.link.device}")
            else:
                self.status_message = self.link.error or "Oczekiwanie na ESP32"
                self.logs.append(self.status_message)
                self.networks.clear()
                self.selected.clear()
                self.pending_scan = None
                self.pending_signals = None
                self.active_stop = None
            self.dirty = True
        elif not connected and self.link.error and self.status_message != self.link.error:
            self.status_message = self.link.error
            self.dirty = True
        for line in lines:
            self._handle_line(line)
        now = self.now()
        if self.pending_scan and now >= self.pending_scan["deadline"]:
            if self.pending_scan["phase"] == "direct" and not self.networks and self.link.send("show_scan_results"):
                self.pending_scan = {"deadline": now + 6, "phase": "fallback", "last": now}
            else:
                self._finish_scan()
        if self.pending_scan and self.pending_scan["phase"] == "fallback" and self.networks and now - self.pending_scan["last"] > 1.3:
            self._finish_scan()
        if self.pending_signals and now >= self.pending_signals["deadline"]:
            self._finish_signals()
        event = self.buttons.poll()
        if event:
            self.button(event)
        if self.dirty or now - self.last_render > 1.0:
            self.display.show(self.render())
            self.last_render = now
            self.dirty = False

    def _fit(self, draw, value: str, max_width: int, font=None) -> str:
        font = font or self.font
        value = str(value)
        if draw.textbbox((0, 0), value, font=font)[2] <= max_width:
            return value
        while value and draw.textbbox((0, 0), value + "…", font=font)[2] > max_width:
            value = value[:-1]
        return value + "…"

    def _wrap(self, draw, value: str, max_width: int) -> list[str]:
        result = []
        for raw in value.splitlines() or [""]:
            while raw:
                end = len(raw)
                while end > 1 and draw.textbbox((0, 0), raw[:end], font=self.small_font)[2] > max_width:
                    end -= 1
                result.append(raw[:end])
                raw = raw[end:]
            if not result:
                result.append("")
        return result

    def render(self):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (SIZE, SIZE), BG)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 127, 17), fill=PANEL)
        draw.rectangle((0, 114, 127, 127), fill=PANEL)
        indicator = GREEN if self.link.connected else RED
        draw.ellipse((116, 5, 122, 11), fill=indicator)
        title = {"home": "JanOS", "wifi": "Wi-Fi", "networks": "Sieci Wi-Fi",
                 "network": "Siec", "sniffer": "Sniffer", "actions": "Akcje RF",
                 "beacon": "Beacon spam", "portal": "Portal", "evil": "Evil Twin",
                 "inside": "ARP / MITM", "wardrive": "Wardrive", "gps": "GPS",
                 "bluetooth": "Bluetooth", "subghz": "SubGHz", "radio_tools": "Radio",
                 "sd": "Karta SD", "device": "Urzadzenie", "signal": "Sygnal",
                 "editor_actions": "Komenda"}.get(self._menu(), self._menu())
        if self.view in ("log", "scan", "loading", "confirm"):
            title = self.title if self.view == "log" else {"scan": "Skanowanie", "loading": self.title, "confirm": "Potwierdz"}[self.view]
        elif self.view == "editor":
            title = "Komenda UART"
        elif self.view == "status":
            title = "Status"
        draw.text((5, 2), self._fit(draw, title, 106, self.title_font), font=self.title_font, fill=CYAN)

        if self.view == "menu":
            items = self._items(self._menu())
            index = min(self.stack[-1][1], max(0, len(items) - 1))
            start = max(0, min(index - 2, len(items) - 6))
            for row, (label, _) in enumerate(items[start:start + 6]):
                y = 20 + row * 15
                active = start + row == index
                if active:
                    draw.rounded_rectangle((2, y, 125, y + 14), radius=3, fill=(25, 77, 95))
                draw.text((6, y + 1), self._fit(draw, label, 116), font=self.font,
                          fill=WHITE if active else MUTED)
            if len(items) > 6:
                draw.text((109, 99), f"{index + 1}/{len(items)}", font=self.small_font, fill=CYAN)
            footer = "JOY ^v O:OK <:WROC"
        elif self.view == "log":
            wrapped = []
            for line in self.logs:
                wrapped.extend(self._wrap(draw, line, 118))
            if not wrapped:
                wrapped = ["Czekam na odpowiedz..."]
            offset = min(self.log_scroll, max(0, len(wrapped) - 8))
            start = max(0, len(wrapped) - 8 - offset)
            for row, line in enumerate(wrapped[start:start + 8]):
                fill = YELLOW if line.startswith(">") else WHITE
                draw.text((4, 20 + row * 11), line, font=self.small_font, fill=fill)
            footer = "JOY ^v O:OST <:WROC"
        elif self.view == "editor":
            draw.text((5, 24), "Komenda:", font=self.small_font, fill=MUTED)
            for row, line in enumerate(self._wrap(draw, self.editor_text[-65:], 118)[-3:]):
                draw.text((5, 37 + row * 11), line, font=self.small_font, fill=WHITE)
            char = self.CHARS[self.editor_index]
            draw.rounded_rectangle((43, 77, 85, 105), radius=3, fill=(25, 77, 95))
            draw.text((55, 80), char, font=self.title_font, fill=CYAN)
            footer = "JOY ^v O:+ <:OPC"
        elif self.view == "confirm":
            draw.text((5, 27), "Wykonac komende?", font=self.font, fill=YELLOW)
            for row, line in enumerate(self._wrap(draw, self.confirm_label, 116)[:4]):
                draw.text((5, 47 + row * 12), line, font=self.small_font, fill=WHITE)
            footer = "JOY O:TAK <:NIE"
        elif self.view == "scan":
            draw.text((5, 33), "Skan Wi-Fi...", font=self.font, fill=CYAN)
            draw.text((5, 58), f"Znaleziono: {len(self.networks)}", font=self.font, fill=WHITE)
            footer = "JOY <:WROC"
        elif self.view == "loading":
            draw.text((5, 38), "Pobieram liste...", font=self.font, fill=CYAN)
            footer = "JOY <:WROC"
        else:
            status = [self.status_message,
                      "ESP: " + ("polaczony" if self.link.connected else "brak"),
                      "Port: " + (self.link.device or "auto"),
                      f"Sieci: {len(self.networks)}  AP: {len(self.selected)}",
                      "Akcja: " + (self.active_name or "brak")]
            y = 23
            for entry in status:
                for line in self._wrap(draw, entry, 118)[:2]:
                    draw.text((5, y), line, font=self.small_font, fill=WHITE)
                    y += 12
            footer = "JOY <:WROC"
        draw.text((4, 116), footer, font=self.small_font, fill=MUTED)
        return image

    def close(self):
        if self.active_stop and self.link.connected:
            self.link.send(self.active_stop)
        self.link.close()
        self.buttons.close()
        self.display.close()

    def _show_splash(self, seconds: float):
        if seconds == 0:
            return
        from PIL import Image, ImageOps

        with Image.open(SPLASH_IMAGE) as source:
            frame = ImageOps.pad(source.convert("RGB"), (SIZE, SIZE),
                                 method=Image.Resampling.LANCZOS, color="white")
        self.display.show(frame)
        deadline = self.now() + seconds
        while (remaining := deadline - self.now()) > 0:
            time.sleep(min(0.05, remaining))

    def run(self, *, splash_seconds: float = DEFAULT_SPLASH_SECONDS):
        try:
            self._show_splash(splash_seconds)
            while True:
                self.tick()
                time.sleep(0.04)
        finally:
            self.close()


def main():
    parser = argparse.ArgumentParser(description="JanOS dla Seengreat 1.44 LCD HAT")
    parser.add_argument("--port", help="Port ESP32-C5, np. /dev/serial/by-id/...")
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), default=DEFAULT_ROTATION,
                        help="Obrot obrazu zgodnie z ruchem wskazowek zegara (domyslnie: 270 = 90 w lewo)")
    parser.add_argument("--x-offset", type=int, default=2, help="Przesuniecie RAM ekranu X")
    parser.add_argument("--y-offset", type=int, default=3, help="Przesuniecie RAM ekranu Y")
    parser.add_argument("--rgb-panel", action="store_true", help="Zamien tryb BGR na RGB")
    parser.add_argument("--splash-seconds", type=float, default=DEFAULT_SPLASH_SECONDS,
                        help="Czas ekranu powitalnego w sekundach (domyslnie: 3; 0 wylacza)")
    args = parser.parse_args()
    if not math.isfinite(args.splash_seconds) or args.splash_seconds < 0:
        parser.error("--splash-seconds musi byc nieujemna, skonczona liczba")
    from hardware import Buttons, Display

    display = Display(rotation=args.rotation, x_offset=args.x_offset,
                      y_offset=args.y_offset, bgr=not args.rgb_panel)
    try:
        buttons = Buttons()
    except Exception:
        display.close()
        raise
    def stop_service(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop_service)
    try:
        ui = JanOSUI(display, buttons, JanOSLink(args.port))
    except BaseException:
        # Construction can fail before JanOSUI.run() owns the resources.
        buttons.close()
        display.close()
        raise
    ui.run(splash_seconds=args.splash_seconds)


if __name__ == "__main__":
    main()
