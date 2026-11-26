"""Tests for the pipeline comparison of the eval suite (story 028)."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import evals.pipelines as pipelines
import evals.run_evals as run_evals

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "evals" / "cases"
RUNNER = ROOT / "evals" / "run_evals.py"


def cases(**match):
    """Eval cases whose fields equal every ``match`` value."""
    return [c for c in run_evals.load_cases(CASES_DIR) if all(c.get(k) == v for k, v in match.items())]


def one(case_id):
    """The eval case with ``case_id``."""
    return next(c for c in run_evals.load_cases(CASES_DIR) if c["id"] == case_id)


class DriftCasesTest(unittest.TestCase):
    """The meaning-drift cases exist per language and stay invisible to ``pe check``."""

    def test_three_drift_kinds_per_language(self):
        for code in ("en", "vi", "ja"):
            kinds = sorted(c["drift"]["kind"] for c in cases(lang=code, category="drift"))
            self.assertEqual(kinds, ["conditional", "negation", "scope"], code)

    def test_check_misses_every_drift(self):
        for case in cases(category="drift"):
            result = run_evals.evaluate_case(case)
            self.assertTrue(result["ok"], case["id"])
            self.assertEqual(result["fidelity"], "MISSED")

    def test_drift_seen_by_check_makes_the_case_fail(self):
        case = copy.deepcopy(one("en-15-drift-negation"))
        case["drift"]["rewrite"] = "Every patient in the trial responded to the 20 mg dose."
        self.assertFalse(run_evals.evaluate_case(case)["ok"])


class EligibilityTest(unittest.TestCase):
    """Only single-rewrite cases are replayed through the pipelines."""

    def test_eligible_categories(self):
        for case in run_evals.load_cases(CASES_DIR):
            expected = case["category"] in ("prose", "technical", "academic", "accept_warning", "drift")
            self.assertEqual(pipelines.eligible(case), expected, case["id"])


class RunTest(unittest.TestCase):
    """Each pipeline on a faithful case and on a drift case."""

    def test_one_shot_ships_the_drift(self):
        run = pipelines.one_shot(one("vi-13-drift-scope"))
        self.assertEqual((run["steps"], run["caught"], run["check_errors"]), (1, 0, 0))
        self.assertTrue(run["drift_shipped"])

    def test_fast_has_no_entailment_gate(self):
        run = pipelines.run_preset(one("en-14-drift-scope"), "fast")
        self.assertEqual(run["status"], "complete")
        self.assertEqual((run["steps"], run["caught"], run["fix_rounds"]), (1, 0, 0))
        self.assertTrue(run["drift_shipped"])

    def test_standard_catches_the_drift_and_fixes_it(self):
        run = pipelines.run_preset(one("ja-15-drift-conditional"), "standard")
        self.assertEqual(run["status"], "complete")
        self.assertGreaterEqual(run["caught"], 1)
        self.assertEqual(run["fix_rounds"], 1)
        self.assertFalse(run["drift_shipped"])
        # plan, lexis, style (write + judge), then the fix round (write + judge)
        self.assertEqual(run["steps"], 6)

    def test_strict_judges_facts(self):
        run = pipelines.run_preset(one("en-15-drift-negation"), "strict")
        self.assertEqual(run["status"], "complete")
        self.assertFalse(run["drift_shipped"])
        self.assertEqual(run["facts"]["total"], 1)
        self.assertEqual(run["facts"]["kept"], 1)

    def test_faithful_case_needs_no_fix_round(self):
        for preset in ("fast", "standard", "strict"):
            run = pipelines.run_preset(one("en-05-false-positive-accept"), preset)
            self.assertEqual((run["status"], run["fix_rounds"], run["check_warnings"]), ("complete", 0, 0), preset)

    def test_protected_spans_are_masked(self):
        run = pipelines.run_preset(one("en-02-technical-code"), "standard")
        self.assertEqual((run["status"], run["check_errors"]), ("complete", 0))


class CompareTest(unittest.TestCase):
    """The comparison over the whole case set backs the default preset."""

    @classmethod
    def setUpClass(cls):
        """Run every pipeline once over all cases."""
        cls.report = pipelines.compare(run_evals.load_cases(CASES_DIR))

    def test_every_run_completes(self):
        self.assertTrue(self.report["ok"])
        self.assertEqual(list(self.report["summary"]), list(pipelines.PIPELINES))

    def test_only_gated_presets_catch_drift(self):
        summary = self.report["summary"]
        drift = summary["one-shot"]["drift_cases"]
        self.assertGreaterEqual(drift, 9)
        for name in ("one-shot", "fast"):
            self.assertEqual((summary[name]["drift_caught"], summary[name]["drift_shipped"]), (0, drift), name)
        for name in ("standard", "strict"):
            self.assertEqual((summary[name]["drift_caught"], summary[name]["drift_shipped"]), (drift, 0), name)

    def test_cost_grows_with_the_preset(self):
        steps = [self.report["summary"][name]["steps"] for name in pipelines.PIPELINES]
        self.assertEqual(steps[0], steps[1])
        self.assertLess(steps[1], steps[2])
        self.assertLess(steps[2], steps[3])

    def test_final_texts_pass_check(self):
        for name, row in self.report["summary"].items():
            self.assertEqual(row["check_errors"], 0, name)

    def test_table_lists_every_pipeline(self):
        table = pipelines.build_table(self.report["summary"])
        for name in pipelines.PIPELINES:
            self.assertIn(name, table)


class CliTest(unittest.TestCase):
    """``--pipeline`` selects the compared pipelines."""

    def run_cli(self, *args):
        """Run the eval runner with ``args``; return the exit code and the JSON report."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            proc = subprocess.run([sys.executable, str(RUNNER), "--quiet", "--json", str(out), *args],
                                  capture_output=True, text=True, encoding="utf-8")
            return proc.returncode, json.loads(out.read_text(encoding="utf-8")) if out.exists() else None

    def test_selected_pipelines_only(self):
        code, report = self.run_cli("--lang", "en", "--pipeline", "strict", "--pipeline", "one-shot")
        self.assertEqual(code, 0)
        self.assertEqual(report["pipelines"]["pipelines"], ["one-shot", "strict"])
        self.assertEqual({r["lang"] for r in report["pipelines"]["runs"]}, {"en"})

    def test_none_skips_the_comparison(self):
        code, report = self.run_cli("--pipeline", "none")
        self.assertEqual(code, 0)
        self.assertIsNone(report["pipelines"])

    def test_unknown_pipeline_is_a_usage_error(self):
        self.assertEqual(self.run_cli("--pipeline", "turbo")[0], 2)


if __name__ == "__main__":
    unittest.main()
