"""Check the joystick workflow without an LCD or an ESP32."""

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class FakeLink:
    def __init__(self):
        self.connected = True
        self.device = "/dev/ttyUSB0"
        self.error = None
        self.sent = []
        self.lines = []

    def poll(self):
        lines, self.lines = self.lines, []
        return lines

    def send(self, command):
        self.sent.append(command)
        return self.connected

    def close(self):
        pass


class FakeDisplay:
    def __init__(self):
        self.frames = []

    def show(self, frame):
        self.frames.append(frame)

    def close(self):
        pass


class FakeButtons:
    def poll(self):
        return None

    def close(self):
        pass


class AppTests(unittest.TestCase):
    def make_ui(self):
        self.link = FakeLink()
        self.clock = [0.0]
        with patch.object(app, "_font", return_value=object()):
            ui = app.JanOSUI(FakeDisplay(), FakeButtons(), self.link, now=lambda: self.clock[0])
        ui.render = lambda: "frame"
        return ui

    def test_wifi_scan_populates_network_menu_and_selects_target(self):
        ui = self.make_ui()
        ui.button("select")  # Wi-Fi
        ui.button("select")  # Scan
        self.assertEqual(self.link.sent, ["unselect_networks", "scan_networks"])
        self.assertEqual(ui.view, "scan")
        ui._handle_line('"1","My, Lab","vendor","AA:BB:CC:DD:EE:FF","6","WPA2","-42","2.4G"')
        ui._handle_line("Scan results printed")
        self.assertEqual(ui._menu(), "networks")
        self.assertEqual(ui.networks["1"]["ssid"], "My, Lab")
        ui.button("select")  # Network details
        ui._do("toggle:1")
        self.assertEqual(ui.selected, {"1"})
        self.assertEqual(self.link.sent[-2:], ["unselect_networks", "select_networks 1"])

    def test_live_monitor_stops_when_log_is_closed(self):
        ui = self.make_ui()
        ui._do("live:subghz_stop:subghz_weather")
        self.assertEqual(ui.active_stop, "subghz_stop")
        ui.button("back")
        self.assertEqual(self.link.sent, ["subghz_weather", "subghz_stop"])
        self.assertIsNone(ui.active_stop)
        self.assertEqual(ui.view, "menu")

    def test_confirm_does_not_send_until_select(self):
        ui = self.make_ui()
        ui._do("confirm:start_blackout")
        self.assertEqual(ui.view, "confirm")
        self.assertFalse(self.link.sent)
        ui.button("back")
        self.assertFalse(self.link.sent)
        ui._do("confirm:start_blackout")
        ui.button("select")
        self.assertEqual(self.link.sent, ["start_blackout"])

    def test_confirmed_subghz_monitor_uses_radio_stop(self):
        ui = self.make_ui()
        ui._do("confirm_live:subghz_stop:subghz_jam")
        ui.button("select")
        ui.button("back")
        self.assertEqual(self.link.sent, ["subghz_jam", "subghz_stop"])

    def test_editor_action_menu_can_return_and_send(self):
        ui = self.make_ui()
        ui._do("editor:version")
        ui.button("back")
        self.assertEqual(ui._menu(), "editor_actions")
        ui.button("back")
        self.assertEqual(ui.view, "editor")
        ui.button("back")
        ui.button("select")  # Send
        self.assertEqual(self.link.sent, ["version"])
        self.assertEqual(ui.view, "log")

    def test_back_during_scan_cancels_auto_open(self):
        ui = self.make_ui()
        ui._do("scan")
        ui.button("back")
        self.assertIsNone(ui.pending_scan)
        self.assertEqual(self.link.sent[-1], "stop")
        ui._handle_line("Scan results printed")
        self.assertEqual(ui._menu(), "home")

    def test_disconnect_clears_stale_network_indices(self):
        ui = self.make_ui()
        ui.tick()  # Initial connection transition
        ui.networks["3"] = {"index": "3", "ssid": "old"}
        ui.selected.add("3")
        self.link.connected = False
        self.link.error = "unplugged"
        ui.tick()
        self.assertFalse(ui.networks)
        self.assertFalse(ui.selected)
        self.assertEqual(ui.status_message, "unplugged")

    def test_subghz_list_ends_on_marker(self):
        ui = self.make_ui()
        ui._do("signals:mem")
        ui._handle_line("[SUBGHZ_LIST] idx=2 type=HOLTEK freq=433.92 name=garage")
        ui._handle_line("[SUBGHZ_LIST_END] count=1 source=mem")
        self.assertIsNone(ui.pending_signals)
        self.assertEqual(ui._menu(), "signals:mem")
        self.assertEqual(ui.signals["mem"]["2"]["name"], "garage")


if __name__ == "__main__":
    unittest.main()
