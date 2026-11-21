"""Tests for the evaluation suite (story 011).

Verifies the smoke test cases across en, vi, ja, ensures schemas are valid,
and tests that the evaluation runner produces valid reports and summary tables.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

import _path  # noqa: F401
import evals.run_evals as run_evals

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "evals" / "cases"
RUNNER = ROOT / "evals" / "run_evals.py"


class EvalCasesTest(unittest.TestCase):
    """Verify evaluation case files, counts, and schemas."""

    def test_smoke_set_count_and_language_coverage(self):
        cases = run_evals.load_cases(CASES_DIR)
        self.assertGreaterEqual(len(cases), 10, "MVP smoke set must have at least 10 cases")
        languages = {c.get("lang") for c in cases}
        self.assertTrue({"en", "vi", "ja"}.issubset(languages),
                        f"Must cover en, vi, and ja; found {languages}")

    def test_case_schemas(self):
        for path in CASES_DIR.rglob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("id", data, f"missing id in {path}")
            self.assertIn("lang", data, f"missing lang in {path}")
            self.assertIn("category", data, f"missing category in {path}")
            if data["category"] == "triggers":
                self.assertIn("prompts", data, f"missing prompts in {path}")
            elif data["category"] == "variants":
                self.assertIn("input", data, f"missing input in {path}")
                self.assertIn("variants", data, f"missing variants in {path}")
                self.assertGreaterEqual(len(data["variants"]), 2)
            else:
                self.assertIn("input", data, f"missing input in {path}")
                self.assertIn("rewrite", data, f"missing rewrite in {path}")


class EvalRunnerTest(unittest.TestCase):
    """Verify evaluation runner execution and output formatting."""

    def test_eval_runner_api(self):
        code, report = run_evals.run_evals(cases_dir=CASES_DIR, quiet=True)
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["total"], 10)
        self.assertEqual(report["passed"], report["total"])
        self.assertEqual(report["pass_rate"], 1.0)
        for lang_code in ("en", "vi", "ja"):
            self.assertIn(lang_code, report["by_lang"])
            self.assertEqual(report["by_lang"][lang_code]["pass_rate"], 1.0)

    def test_eval_runner_cli(self):
        proc = subprocess.run([sys.executable, str(RUNNER)], capture_output=True,
                              text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("EVALUATION SUMMARY", proc.stdout)
        self.assertIn("Language Breakdown", proc.stdout)
        self.assertIn("en:", proc.stdout)
        self.assertIn("vi:", proc.stdout)
        self.assertIn("ja:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
