import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CardputerPackageTests(unittest.TestCase):
    def test_stage_contains_shared_core_and_generated_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            env = {
                **os.environ,
                "STAGE": str(stage),
                "APP_INSTALL_DIR": "/usr/share/APPLaunch/apps/janos-cardputer",
                "INSTALL_PREFIX": "/usr/share/APPLaunch",
            }
            subprocess.run(
                ["bash", str(ROOT / "CardputerZero/packaging/stage.sh")],
                cwd=ROOT,
                env=env,
                check=True,
            )
            app = stage / "usr/share/APPLaunch/apps/janos-cardputer"
            self.assertTrue((app / "JanOS_app.py").is_file())
            self.assertTrue((app / "janos_core.py").is_file())
            self.assertTrue((app / "projectzero_commands.py").is_file())
            self.assertTrue((app / "CardputerZero/app/controller.py").is_file())
            self.assertTrue((app / "CardputerZero/generated/command_catalog.json").is_file())
            self.assertTrue((stage / "usr/share/APPLaunch/bin/janos-cardputer").is_file())


if __name__ == "__main__":
    unittest.main()
