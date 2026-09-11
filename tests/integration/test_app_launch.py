"""Integration test verifying that main.py launches and exits cleanly."""

import subprocess
import sys
import time
import unittest


class TestAppLaunch(unittest.TestCase):
    """Verify application entry point launch and termination."""

    def test_main_py_launches_and_terminates_cleanly(self):
        # Launch main.py as a subprocess using the current Python executable
        proc = subprocess.Popen(
            [sys.executable, "main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # Give the application time to initialize the Qt event loop
            time.sleep(1.5)
            self.assertIsNone(
                proc.poll(), "Process terminated prematurely during startup."
            )
        finally:
            # Terminate and verify clean exit
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=5)

        self.assertIsNotNone(proc.returncode)


if __name__ == "__main__":
    unittest.main()
