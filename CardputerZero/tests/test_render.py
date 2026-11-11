import importlib.util
import unittest

from CardputerZero.app.controller import Controller
from CardputerZero.app.render import Renderer


class CardputerRenderTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
    def test_every_primary_screen_renders_320_by_170(self):
        controller = Controller(demo=True)
        renderer = Renderer()
        try:
            for screen in ("splash", "home", "ports", "categories", "files", "settings", "about"):
                controller.screen = screen
                image = renderer.draw(controller.view())
                self.assertEqual((320, 170), image.size, screen)
                self.assertEqual("RGB", image.mode, screen)
        finally:
            controller.close()


if __name__ == "__main__":
    unittest.main()
