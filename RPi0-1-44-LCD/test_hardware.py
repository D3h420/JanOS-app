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
        display.show(FakeImage())
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
            self.assertEqual([c[1] for c in gpio.claims if c[0] == "in"], [17, 18, 22, 23])
            self.assertIsNone(buttons.poll())
            gpio.levels[17] = 0
            self.assertIsNone(buttons.poll())
            clock[0] = 0.031
            self.assertEqual(buttons.poll(), "up")
            self.assertIsNone(buttons.poll())
            clock[0] = 0.482
            self.assertEqual(buttons.poll(), "up")
            self.assertIsNone(buttons.poll())
            gpio.levels[17] = 1
            self.assertIsNone(buttons.poll())
            clock[0] = 0.513
            self.assertIsNone(buttons.poll())
            gpio.levels[23] = 0
            self.assertIsNone(buttons.poll())
            clock[0] = 0.544
            self.assertEqual(buttons.poll(), "back")
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
