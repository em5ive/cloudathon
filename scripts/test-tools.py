"""Focused local tests for dependency cycles, invalid inventory, and payback edge cases."""
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
discovery = runpy.run_path(str(ROOT / "scripts/discover-inventory.py"))
business = runpy.run_path(str(ROOT / "scripts/business-case.py"))


class ToolTests(unittest.TestCase):
    def test_cycle_members_stay_in_same_group(self):
        groups = discovery["strongly_connected"]({"app": {"db"}, "db": {"app"}, "web": {"app"}})
        self.assertIn(["app", "db"], groups)
        self.assertIn(["web"], groups)

    def test_example_dependencies_precede_consumers(self):
        rows = discovery["assign"](ROOT / "migration/inventory.example.csv", ROOT / "migration/dependencies.example.csv")
        wave = {row["application"]: int(row["draft_wave"]) for row in rows}
        self.assertLess(wave["catalog"], wave["orders"])
        self.assertLess(wave["identity"], wave["orders"])
        self.assertLess(wave["orders"], wave["support"])

    def test_unknown_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            dependencies = Path(directory) / "deps.csv"
            dependencies.write_text("application,depends_on\norders,missing\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                discovery["assign"](ROOT / "migration/inventory.example.csv", dependencies)

    def test_nonpositive_savings_has_no_payback(self):
        data = {"scenario": "test", "on_prem_annual": {"a": 100}, "target_annual": {"a": 200}, "one_time_transition": {"a": 50}}
        self.assertIsNone(business["calculate"](data)["break_even_months_after_full_exit"])

    def test_nonfinite_cost_rejected(self):
        with self.assertRaises(ValueError):
            business["calculate"]({"scenario": "test", "on_prem_annual": {"a": float("nan")}})


if __name__ == "__main__":
    unittest.main()
