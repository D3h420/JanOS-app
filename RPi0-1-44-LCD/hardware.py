"""Seeangreat 1.44-inch ST7735S HAT on a Raspberry Pi Zero 2 W.

BCM pin numbers come from the Seeangreat product wiki:
https://seengreat.com/wiki/68/1-44inch-lcd-display

The default 2/3 RAM offset and 0xC8 memory direction follow the standard
128x128 ST7735 1.44-inch panel profile. They can be adjusted for a different
HAT revision. The Raspberry Pi dependencies are loaded only on construction.
"""

from __future__ import annotations

import time
from typing import Literal


WIDTH = 128
HEIGHT = 128

_DC = 25
_RESET = 27
_BACKLIGHT = 24
_BUTTON_PINS = {"up": 17, "down": 18, "select": 22, "back": 23}
ButtonName = Literal["up", "down", "select", "back"]


class Display:
    """Direct SPI display; call :meth:`show` with a 128×128 Pillow image.

    ``rotation`` rotates the supplied image clockwise in software. The panel
    remains in its default ST7735 memory orientation, so RAM offsets are fixed.
    ``spi_hz`` defaults to a conservative 8 MHz for a Pi Zero 2 W.
    """

    def __init__(
        self,
        *,
        rotation: int = 0,
        x_offset: int = 2,
        y_offset: int = 3,
        spi_hz: int = 8_000_000,
        bgr: bool = True,
        gpio_chip: int = 0,
        gpio=None,
        spi=None,
    ) -> None:
        if rotation not in (0, 90, 180, 270):
            raise ValueError("rotation must be 0, 90, 180 or 270 degrees")
        if not (0 <= x_offset <= 127 and 0 <= y_offset <= 31):
            raise ValueError("invalid ST7735S RAM offset")
        if spi_hz <= 0:
            raise ValueError("spi_hz must be positive")

        if gpio is None:
            try:
                import lgpio as gpio
            except ImportError as exc:
                raise RuntimeError("Install python3-lgpio on the Raspberry Pi") from exc
        if spi is None:
            try:
                import spidev
            except ImportError as exc:
                raise RuntimeError("Install python3-spidev on the Raspberry Pi") from exc
            spi = spidev.SpiDev()

        self.rotation = rotation
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.bgr = bgr
        self._gpio = gpio
        self._spi = spi
        self._chip = None
        self._claimed: list[int] = []
        self._closed = False
        try:
            self._chip = gpio.gpiochip_open(gpio_chip)
            for pin, level in ((_DC, 0), (_RESET, 1), (_BACKLIGHT, 0)):
                gpio.gpio_claim_output(self._chip, pin, level)
                self._claimed.append(pin)
            # CE0 (BCM 8) is owned by the kernel SPI driver, not claimed here.
            spi.open(0, 0)
            spi.mode = 0
            spi.bits_per_word = 8
            spi.max_speed_hz = spi_hz
            self._init_panel()
            gpio.gpio_write(self._chip, _BACKLIGHT, 1)
        except BaseException:
            self.close()
            raise

    def _command(self, command: int, data: bytes = b"") -> None:
        self._gpio.gpio_write(self._chip, _DC, 0)
        self._spi.writebytes2(bytes((command,)))
        if data:
            self._gpio.gpio_write(self._chip, _DC, 1)
            self._spi.writebytes2(data)

    def _init_panel(self) -> None:
        gpio = self._gpio
        chip = self._chip
        gpio.gpio_write(chip, _RESET, 1)
        time.sleep(0.01)
        gpio.gpio_write(chip, _RESET, 0)
        time.sleep(0.01)
        gpio.gpio_write(chip, _RESET, 1)
        time.sleep(0.12)

        # ST7735S 128×128 initialization in RGB565 mode.
        self._command(0x01)  # SWRESET
        time.sleep(0.15)
        self._command(0x11)  # SLPOUT
        time.sleep(0.5)
        for command, values in (
            (0xB1, (0x01, 0x2C, 0x2D)),  # frame rate, normal
            (0xB2, (0x01, 0x2C, 0x2D)),  # frame rate, idle
            (0xB3, (0x01, 0x2C, 0x2D, 0x01, 0x2C, 0x2D)),
            (0xB4, (0x07,)),
            (0xC0, (0xA2, 0x02, 0x84)),
            (0xC1, (0xC5,)),
            (0xC2, (0x0A, 0x00)),
            (0xC3, (0x8A, 0x2A)),
            (0xC4, (0x8A, 0xEE)),
            (0xC5, (0x0E,)),
            (0x36, (0xC8 if self.bgr else 0xC0,)),  # MX | MY | BGR/RGB
            (0x3A, (0x05,)),  # 16-bit RGB565
            (0xE0, (0x02, 0x1C, 0x07, 0x12, 0x37, 0x32, 0x29, 0x2D,
                    0x29, 0x25, 0x2B, 0x39, 0x00, 0x01, 0x03, 0x10)),
            (0xE1, (0x03, 0x1D, 0x07, 0x06, 0x2E, 0x2C, 0x29, 0x2D,
                    0x2E, 0x2E, 0x37, 0x3F, 0x00, 0x00, 0x02, 0x10)),
        ):
            self._command(command, bytes(values))
        self._command(0x20)  # INVOFF
        self._command(0x13)  # NORON
        time.sleep(0.01)
        self._command(0x29)  # DISPON
        time.sleep(0.1)

    def show(self, image) -> None:
        """Send one full 128×128 frame; ``image`` may have any Pillow mode."""
        if self._closed:
            raise RuntimeError("display is closed")
        if image.size != (WIDTH, HEIGHT):
            raise ValueError(f"image must be {WIDTH}×{HEIGHT} pixels")
        if self.rotation:
            image = image.rotate(-self.rotation)
        rgb = image.convert("RGB").tobytes()
        pixels = bytearray(WIDTH * HEIGHT * 2)
        for source, target in zip(range(0, len(rgb), 3), range(0, len(pixels), 2)):
            red, green, blue = rgb[source], rgb[source + 1], rgb[source + 2]
            pixels[target] = (red & 0xF8) | (green >> 5)
            pixels[target + 1] = ((green & 0x1C) << 3) | (blue >> 3)

        x0, y0 = self.x_offset, self.y_offset
        x1, y1 = x0 + WIDTH - 1, y0 + HEIGHT - 1
        self._command(0x2A, bytes((x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF)))
        self._command(0x2B, bytes((y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF)))
        self._command(0x2C)  # RAMWR
        self._gpio.gpio_write(self._chip, _DC, 1)
        self._spi.writebytes2(pixels)

    def close(self) -> None:
        """Turn the backlight off and release SPI/GPIO resources."""
        if self._closed:
            return
        self._closed = True
        if self._chip is not None and _BACKLIGHT in self._claimed:
            self._gpio.gpio_write(self._chip, _BACKLIGHT, 0)
        try:
            self._spi.close()
        finally:
            if self._chip is not None:
                for pin in reversed(self._claimed):
                    self._gpio.gpio_free(self._chip, pin)
                self._gpio.gpiochip_close(self._chip)


class Buttons:
    """Four active-low HAT keys, K1/K2/K3/K4 = up/down/select/back.

    ``poll()`` debounces presses. Up/down repeat while held for long menus;
    select/back fire only once so actions cannot start accidentally.
    """

    def __init__(self, *, debounce_s: float = 0.03,
                 repeat_delay_s: float = 0.45,
                 repeat_interval_s: float = 0.12,
                 gpio_chip: int = 0, gpio=None) -> None:
        if debounce_s < 0 or repeat_delay_s <= 0 or repeat_interval_s <= 0:
            raise ValueError("invalid button timing")
        if gpio is None:
            try:
                import lgpio as gpio
            except ImportError as exc:
                raise RuntimeError("Install python3-lgpio on the Raspberry Pi") from exc
        self._gpio = gpio
        self._chip = None
        self._claimed: list[int] = []
        self._closed = False
        self._debounce_s = debounce_s
        self._repeat_delay_s = repeat_delay_s
        self._repeat_interval_s = repeat_interval_s
        self._next_repeat_at: float | None = None
        self._candidate: ButtonName | None = None
        self._stable: ButtonName | None = None
        self._changed_at = time.monotonic()
        try:
            self._chip = gpio.gpiochip_open(gpio_chip)
            for pin in _BUTTON_PINS.values():
                gpio.gpio_claim_input(self._chip, pin, gpio.SET_PULL_UP)
                self._claimed.append(pin)
        except BaseException:
            self.close()
            raise

    def read(self) -> frozenset[ButtonName]:
        """Read raw key levels; returns all currently pressed keys."""
        if self._closed:
            raise RuntimeError("buttons are closed")
        return frozenset(
            name for name, pin in _BUTTON_PINS.items()
            if self._gpio.gpio_read(self._chip, pin) == 0
        )

    def poll(self) -> ButtonName | None:
        """Return the next debounced key-down event or ``None``."""
        pressed = self.read()
        # With multiple pressed keys, K1 has priority over K2, etc.
        current = next((name for name in _BUTTON_PINS if name in pressed), None)
        now = time.monotonic()
        if current != self._candidate:
            self._candidate = current
            self._changed_at = now
        if current != self._stable and now - self._changed_at >= self._debounce_s:
            self._stable = current
            self._next_repeat_at = now + self._repeat_delay_s if current in ("up", "down") else None
            if current is not None:
                return current
        if current == self._stable and current in ("up", "down") and self._next_repeat_at is not None and now >= self._next_repeat_at:
            self._next_repeat_at = now + self._repeat_interval_s
            return current
        return None

    def close(self) -> None:
        """Release the four GPIO inputs."""
        if self._closed:
            return
        self._closed = True
        if self._chip is not None:
            for pin in reversed(self._claimed):
                self._gpio.gpio_free(self._chip, pin)
            self._gpio.gpiochip_close(self._chip)
