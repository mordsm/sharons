"""No provider access required: URL boundary tests."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).with_name("browser_poc.py")
spec = importlib.util.spec_from_file_location("clalit_browser_poc", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PortalUrlBoundaryTests(unittest.TestCase):
    def test_official_portal(self):
        self.assertEqual(module.validate_portal_url("https://e-services.clalit.co.il/"), "https://e-services.clalit.co.il/")

    def test_reject_lookalike_domain(self):
        with self.assertRaises(ValueError):
            module.validate_portal_url("https://e-services.clalit.co.il.attacker.example/")

    def test_reject_http(self):
        with self.assertRaises(ValueError):
            module.validate_portal_url("http://e-services.clalit.co.il/")

    def test_reject_embedded_credentials(self):
        with self.assertRaises(ValueError):
            module.validate_portal_url("https://user:secret@e-services.clalit.co.il/")


if __name__ == "__main__":
    unittest.main()
