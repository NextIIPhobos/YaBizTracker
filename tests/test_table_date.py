from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OrganizationDateColumnTests(unittest.TestCase):
    def test_date_column_is_in_stable_contract(self):
        text = (ROOT / "yabiztracker" / "domain" / "table.py").read_text(encoding="utf-8")
        self.assertIn("APPEARED_DATE = 4", text)
        self.assertIn("SCORE = 14", text)

    def test_date_column_is_rendered_from_first_seen_and_default_sorted(self):
        text = (ROOT / "yabiztracker" / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("\"Дата появления\"", text)
        self.assertIn("o.get(\"first_seen_date\",\"\")", text)
        self.assertIn("first_seen_date", text)
        self.assertIn("Qt.SortOrder.DescendingOrder", text)


if __name__ == "__main__":
    unittest.main()
