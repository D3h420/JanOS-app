import time
import unittest

from CardputerZero.app.controller import Controller


class CardputerControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller(demo=True)
        self.controller.handle("ENTER")

    def tearDown(self):
        self.controller.close()

    def test_home_and_function_navigation(self):
        self.assertEqual("home", self.controller.screen)
        self.controller.selected = 2
        self.controller.handle("ENTER")
        self.assertEqual("categories", self.controller.screen)
        self.controller.handle("ENTER")
        self.assertEqual("commands", self.controller.screen)
        self.assertTrue(self.controller.commands())

    def test_scan_is_real_operation_and_produces_results_screen(self):
        self.controller.selected = 1
        self.controller.handle("ENTER")
        self.assertEqual("log", self.controller.screen)
        self.controller.operation.thread.join(timeout=2)
        self.controller.tick()
        self.assertEqual("scan_results", self.controller.screen)

    def test_raw_console_accepts_keyboard_text(self):
        self.controller.selected = 4
        self.controller.handle("ENTER")
        for character in "version":
            self.controller.handle("TEXT", character)
        self.controller.handle("ENTER")
        self.assertEqual("log", self.controller.screen)
        self.assertEqual("version", self.controller.operation.command)


if __name__ == "__main__":
    unittest.main()
