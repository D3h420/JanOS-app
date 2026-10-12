"""Pure-Python checks for the HAT protocol; no Raspberry Pi required."""

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("hat_hardware", Path(__file__).with_name("hardware.py"))
hardware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hardware)


class FakeGPIO:
    SET_PULL_UP = 32

    def __init__(self):
        self.levels = {}
        self.claims = []

    def gpiochip_open(self, chip):
        self.chip = chip
        return 10

    def gpio_claim_output(self, handle, pin, level):
        self.claims.append(("out", pin, level))
        self.levels[pin] = level

    def gpio_claim_input(self, handle, pin, flags):
        self.claims.append(("in", pin, flags))
        self.levels[pin] = 1

    def gpio_write(self, handle, pin, level):
        self.levels[pin] = level

    def gpio_read(self, handle, pin):
        return self.levels[pin]

    def gpio_free(self, handle, pin):
        self.claims.append(("free", pin))

    def gpiochip_close(self, handle):
        self.claims.append(("close", handle))


class FakeSPI:
    def __init__(self, gpio):
        self.gpio = gpio
        self.transfers = []

    def open(self, bus, device):
        self.bus_device = (bus, device)

    def writebytes2(self, data):
        self.transfers.append((self.gpio.levels[25], bytes(data)))

    def close(self):
        self.closed = True


class FakeImage:
    size = (128, 128)

    def __init__(self):
        self.rotated_by = None

    def rotate(self, angle):
        self.rotated_by = angle
        return self

    def convert(self, mode):
        assert mode == "RGB"
        return self

    def tobytes(self):
        return bytes((255, 0, 0)) + bytes(128 * 128 * 3 - 3)


class HardwareTests(unittest.TestCase):
    def test_display_spi_address_and_rgb565(self):
        gpio = FakeGPIO()
        spi = FakeSPI(gpio)
        original_sleep = hardware.time.sleep
        hardware.time.sleep = lambda _: None
        try:
            display = hardware.Display(gpio=gpio, spi=spi)
        finally:
            hardware.time.sleep = original_sleep
        image = FakeImage()
        display.show(image)
        self.assertEqual(image.rotated_by, -270)
        self.assertEqual(spi.bus_device, (0, 0))
        self.assertEqual(spi.mode, 0)
        self.assertEqual(spi.max_speed_hz, 8_000_000)
        self.assertIn((0, b"\x2a"), spi.transfers)
        self.assertIn((1, b"\x00\x02\x00\x81"), spi.transfers)
        self.assertIn((1, b"\x00\x03\x00\x82"), spi.transfers)
        self.assertEqual(spi.transfers[-1][0], 1)
        self.assertEqual(spi.transfers[-1][1][:4], b"\xf8\x00\x00\x00")
        self.assertEqual(len(spi.transfers[-1][1]), 128 * 128 * 2)
        display.close()
        self.assertEqual(gpio.levels[24], 0)
        self.assertTrue(spi.closed)

    def test_buttons_emit_one_event_per_debounced_press(self):
        gpio = FakeGPIO()
        clock = [0.0]
        original_monotonic = hardware.time.monotonic
        hardware.time.monotonic = lambda: clock[0]
        try:
            buttons = hardware.Buttons(gpio=gpio, debounce_s=0.03)
            self.assertEqual([c[1] for c in gpio.claims if c[0] == "in"],
                             [13, 26, 5, 19, 6])
            self.assertIsNone(buttons.poll())
            gpio.levels[13] = 0
            self.assertIsNone(buttons.poll())
            clock[0] = 0.031
            self.assertEqual(buttons.poll(), "up")
            self.assertIsNone(buttons.poll())
            clock[0] = 0.482
            self.assertEqual(buttons.poll(), "up")
            self.assertIsNone(buttons.poll())
            gpio.levels[13] = 1
            self.assertIsNone(buttons.poll())
            clock[0] = 0.513
            self.assertIsNone(buttons.poll())
            gpio.levels[5] = 0
            self.assertIsNone(buttons.poll())
            clock[0] = 0.544
            self.assertEqual(buttons.poll(), "back")
            self.assertEqual(buttons.last_source, "joy_left")
            buttons.close()
        finally:
            hardware.time.monotonic = original_monotonic

    def test_joystick_directions_and_center(self):
        gpio = FakeGPIO()
        clock = [0.0]
        original_monotonic = hardware.time.monotonic
        hardware.time.monotonic = lambda: clock[0]
        try:
            buttons = hardware.Buttons(gpio=gpio)
            gpio.levels.update({17: 0, 18: 0, 22: 0, 23: 0})
            self.assertFalse(buttons.read_raw())
            self.assertFalse(buttons.read())
            for name, pin, action in (
                ("joy_up", 13, "up"),
                ("joy_down", 26, "down"),
                ("joy_left", 5, "back"),
                ("joy_right", 19, "select"),
                ("joy_center", 6, "select"),
            ):
                gpio.levels[pin] = 0
                self.assertEqual(buttons.read_raw(), {name})
                self.assertIsNone(buttons.poll())
                clock[0] += 0.031
                self.assertEqual(buttons.poll(), action)
                self.assertEqual(buttons.last_source, name)
                gpio.levels[pin] = 1
                self.assertIsNone(buttons.poll())
                clock[0] += 0.031
                self.assertIsNone(buttons.poll())
            buttons.close()
        finally:
            hardware.time.monotonic = original_monotonic

    def test_rgb_panel_option_changes_memory_order(self):
        gpio = FakeGPIO()
        spi = FakeSPI(gpio)
        original_sleep = hardware.time.sleep
        hardware.time.sleep = lambda _: None
        try:
            display = hardware.Display(gpio=gpio, spi=spi, bgr=False)
        finally:
            hardware.time.sleep = original_sleep
        index = spi.transfers.index((0, b"\x36"))
        self.assertEqual(spi.transfers[index + 1], (1, b"\xc0"))
        display.close()


if __name__ == "__main__":
    unittest.main()
