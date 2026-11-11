"""Cardputer Zero keyboard input through Linux evdev."""

from __future__ import annotations

import os
import select


class Keyboard:
    """Discover a keyboard and normalize evdev events for the controller."""

    def __init__(self) -> None:
        from evdev import InputDevice, ecodes, list_devices

        self.ecodes = ecodes
        self.devices = []
        self.shift = False
        explicit = (
            os.environ.get("APPLAUNCH_KEYBOARD_DEVICE")
            or os.environ.get("LV_LINUX_KEYBOARD_DEVICE")
        )
        candidates = [explicit] if explicit else list_devices()
        for path in candidates:
            if not path:
                continue
            try:
                device = InputDevice(path)
                keys = device.capabilities().get(ecodes.EV_KEY, [])
                if ecodes.KEY_ENTER in keys and ecodes.KEY_ESC in keys:
                    self.devices.append(device)
                else:
                    device.close()
            except (OSError, PermissionError):
                continue
        if not self.devices:
            raise RuntimeError("No readable Cardputer keyboard; check input group/device path")

    def events(self, *, editing: bool = False) -> list[tuple[str, str]]:
        from evdev import ecodes

        ready, _, _ = select.select(self.devices, [], [], 0)
        normalized: list[tuple[str, str]] = []
        for device in ready:
            try:
                source = device.read()
            except OSError:
                continue
            for event in source:
                if event.type != ecodes.EV_KEY:
                    continue
                if event.code in {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}:
                    self.shift = event.value != 0
                    continue
                if event.value not in {1, 2}:
                    continue
                mapped = self._map(event.code, editing=editing)
                if mapped:
                    normalized.append(mapped)
        return normalized

    def _map(self, code: int, *, editing: bool) -> tuple[str, str] | None:
        e = self.ecodes
        fixed = {
            e.KEY_UP: "UP",
            e.KEY_DOWN: "DOWN",
            e.KEY_LEFT: "LEFT",
            e.KEY_RIGHT: "RIGHT",
            e.KEY_ENTER: "ENTER",
            e.KEY_KPENTER: "ENTER",
            e.KEY_ESC: "ESC",
            e.KEY_HOME: "HOME",
            e.KEY_PAGEUP: "PAGEUP",
            e.KEY_PAGEDOWN: "PAGEDOWN",
            e.KEY_BACKSPACE: "BACKSPACE",
            e.KEY_DELETE: "DELETE",
            e.KEY_TAB: "TAB",
        }
        if code in fixed:
            return fixed[code], ""
        name = e.KEY.get(code, "")
        if not isinstance(name, str):
            return None
        if not editing:
            # Kernel mappings on Cardputer Zero expose fn+F/X/Z/C as arrows,
            # but accepting the letters keeps alternate images usable.
            navigation = {"KEY_F": "UP", "KEY_X": "DOWN", "KEY_Z": "LEFT", "KEY_C": "RIGHT"}
            if name in navigation:
                return navigation[name], ""
        if name.startswith("KEY_") and len(name) == 5 and name[-1].isalpha():
            character = name[-1].upper() if self.shift else name[-1].lower()
            return "TEXT", character
        if name.startswith("KEY_") and len(name) == 5 and name[-1].isdigit():
            shifted = {
                "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
                "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
            }
            character = shifted[name[-1]] if self.shift else name[-1]
            return "TEXT", character
        if code == e.KEY_SPACE:
            return "TEXT", " "
        punctuation = {
            e.KEY_MINUS: ("-", "_"), e.KEY_EQUAL: ("=", "+"),
            e.KEY_LEFTBRACE: ("[", "{"), e.KEY_RIGHTBRACE: ("]", "}"),
            e.KEY_BACKSLASH: ("\\", "|"), e.KEY_SEMICOLON: (";", ":"),
            e.KEY_APOSTROPHE: ("'", '"'), e.KEY_GRAVE: ("`", "~"),
            e.KEY_COMMA: (",", "<"), e.KEY_DOT: (".", ">"),
            e.KEY_SLASH: ("/", "?"),
        }
        if code in punctuation:
            return "TEXT", punctuation[code][self.shift]
        return None

    def close(self) -> None:
        for device in self.devices:
            device.close()

