import unittest
from pathlib import Path


class ModalRegressionTests(unittest.TestCase):
    def test_modal_dismissal_only_targets_the_backdrop(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("event.target.classList.contains('modal-backdrop')", source)
        self.assertIn("const target = event.target.closest('button')", source)
        self.assertNotIn("event.target.closest('button, [data-close-modal]')", source)


if __name__ == "__main__":
    unittest.main()
