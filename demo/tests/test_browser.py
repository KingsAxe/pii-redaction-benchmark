"""Execute the browser's actual Unicode/rendering helpers without dependencies."""
import subprocess
import unittest
from pathlib import Path


class BrowserHelperTests(unittest.TestCase):
    def test_browser_code_point_conversion_and_safe_text_nodes(self):
        result = subprocess.run(["node", str(Path(__file__).with_name("browser_checks.mjs"))],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
