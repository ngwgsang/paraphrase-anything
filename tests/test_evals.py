"""Tests for the evaluation suite (story 011).

Verifies the v0.3 case set across en, vi, ja, ensures schemas are valid, and tests that the
runner scores formats, check fixtures, and per-language gates and produces valid reports.
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

    def test_case_count_and_language_coverage(self):
        cases = run_evals.load_cases(CASES_DIR)
        self.assertGreaterEqual(len(cases), 30, "v0.3 set must have at least 30 cases")
        for code in ("en", "vi", "ja"):
            own = [c for c in cases if c["lang"] == code]
            self.assertGreaterEqual(len(own), 10, f"{code} needs at least 10 cases")
            categories = {c["category"] for c in own}
            for needed in ("prose", "technical", "academic", "variants", "triggers",
                           "accept_warning", "format", "check_fixture"):
                self.assertIn(needed, categories, f"{code} has no {needed} case")
            formats = {c.get("format") for c in own}
            self.assertTrue({"srt", "vtt"} & formats, f"{code} has no subtitle case")
            self.assertIn("markdown", formats, f"{code} has no Markdown case")

    def test_fixtures_cover_false_and_true_positives(self):
        fixtures = [c for c in run_evals.load_cases(CASES_DIR) if c["category"] == "check_fixture"]
        self.assertTrue(any(c["expect"].get("ok") is True for c in fixtures), "no clean fixture")
        self.assertTrue(any(c["expect"].get("errors") for c in fixtures), "no error fixture")
        self.assertTrue(any(c["expect"].get("warnings") for c in fixtures), "no warning fixture")
        for case in fixtures:
            self.assertIn("note", case, f"{case['id']} must explain what it pins down")

    def test_case_ids_match_file_names(self):
        for path in CASES_DIR.rglob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["id"], f"{path.parent.name}-{path.stem}")
            self.assertEqual(data["lang"], path.parent.name)

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
            elif data["category"] == "format":
                self.assertIn(data.get("format"), run_evals.formats.FORMATS, str(path))
                self.assertIn("input", data, f"missing input in {path}")
                self.assertTrue(data.get("segments"), f"missing segments in {path}")
            else:
                self.assertIn("input", data, f"missing input in {path}")
                self.assertIn("rewrite", data, f"missing rewrite in {path}")
            if data["category"] == "check_fixture":
                self.assertTrue(data["expect"] and set(data["expect"]) <= {"ok", "errors", "warnings"},
                                str(path))
            if data["category"] == "drift":
                drift = data["drift"]
                self.assertIn(drift["kind"], ("scope", "negation", "conditional"), str(path))
                self.assertTrue(drift["rewrite"] and drift["reason"], str(path))
                self.assertNotEqual(drift["rewrite"], data["rewrite"], str(path))
                self.assertIn("entail", (drift["forward"], drift["backward"]), str(path))
                self.assertNotEqual((drift["forward"], drift["backward"]), ("entail", "entail"), str(path))


class TriggerTermsTest(unittest.TestCase):
    """Verify trigger terms come from SKILL.md and the heuristic handles edge cases."""

    def test_terms_derived_from_skill_description(self):
        terms = run_evals.skill_trigger_terms()
        for expected in ("paraphrase", "rewrite", "say this differently", "alternative versions",
                         "variants", "viết lại", "言い換え"):
            self.assertIn(expected, terms)

    def test_every_negative_term_is_not_a_positive_term(self):
        positive = run_evals.skill_trigger_terms()
        for terms in run_evals.load_negative_terms().values():
            for term in terms:
                self.assertFalse(any(p in term for p in positive), term)

    def test_noun_in_prompt_does_not_veto(self):
        self.assertTrue(run_evals.evaluate_prompt_trigger("Rewrite this summary", "en"))
        self.assertFalse(run_evals.evaluate_prompt_trigger("Summarize this article", "en"))


class CaseScoringTest(unittest.TestCase):
    """Verify that the runner fails cases that break their contract."""

    SRT = "1\n00:00:01,000 --> 00:00:03,000\nThe shop opens at 9.\n"

    def test_fixture_mismatch_fails(self):
        case = {"id": "x", "lang": "en", "category": "check_fixture", "input": "We sold 5 cars.",
                "rewrite": "We sold 6 cars.", "expect": {"ok": True}}
        result = run_evals.evaluate_case(case)
        self.assertFalse(result["ok"])
        self.assertEqual(result["fidelity"], "MISMATCH")
        self.assertEqual(result["stats"], {"fixtures": 1, "fixtures_matched": 0})

    def test_fixture_match_passes(self):
        case = {"id": "x", "lang": "en", "category": "check_fixture", "input": "We sold 5 cars.",
                "rewrite": "We sold 6 cars.",
                "expect": {"ok": False, "errors": ["number_missing", "number_extra"]}}
        self.assertTrue(run_evals.evaluate_case(case)["ok"])

    def test_format_case_round_trip(self):
        case = {"id": "x", "lang": "en", "category": "format", "format": "srt", "input": self.SRT,
                "segments": {"1": "Doors open at 9."},
                "expected_invariants": {"numbers": ["00:00:01,000 --> 00:00:03,000"]}}
        result = run_evals.evaluate_case(case)
        self.assertTrue(result["ok"], result["details"])
        self.assertIn("subtitle_warnings", result["details"])

    def test_format_invariants_are_read_from_the_rebuilt_file(self):
        case = {"id": "x", "lang": "en", "category": "format", "format": "srt", "input": self.SRT,
                "segments": {"1": "Doors open at 9."}, "expected_invariants": {"terms": ["missing text"]}}
        result = run_evals.evaluate_case(case)
        self.assertFalse(result["ok"])
        self.assertEqual(result["details"]["missing_invariants"], ["term:missing text"])

    def test_format_case_rejects_broken_cue(self):
        case = {"id": "x", "lang": "en", "category": "format", "format": "srt", "input": self.SRT,
                "segments": {"1": "Doors open\n\nat 9."}}
        result = run_evals.evaluate_case(case)
        self.assertFalse(result["ok"])
        self.assertIn("format_error", result["details"])

    def test_format_case_checks_prose(self):
        case = {"id": "x", "lang": "en", "category": "format", "format": "srt", "input": self.SRT,
                "segments": {"1": "Doors open at 10."}}
        result = run_evals.evaluate_case(case)
        self.assertFalse(result["ok"])
        self.assertEqual(result["fidelity"], "FAIL")


class LanguageScoresTest(unittest.TestCase):
    """Verify per-language aggregation and the decision gate."""

    def test_score_language(self):
        results = [
            {"ok": True, "stats": {"check_ok": True, "warnings_raised": 1, "warnings_accepted": 1,
                                   "band": "within"}},
            {"ok": True, "stats": {"check_ok": True, "warnings_raised": 0, "warnings_accepted": 0,
                                   "band": "above"}},
            {"ok": False, "stats": {"prompts": 4, "prompts_correct": 3}},
            {"ok": True, "stats": {"check_ok": True, "warnings_raised": 0, "warnings_accepted": 0,
                                   "pair_overlap": 0.2}},
        ]
        scores = run_evals.score_language(results)
        self.assertEqual(scores["pass_rate"], 0.75)
        self.assertEqual(scores["check_pass_rate"], 1.0)
        self.assertEqual(scores["accepted_warning_rate"], 0.3333)
        self.assertEqual(scores["band_rate"], 0.5)
        self.assertEqual(scores["variant_overlap"], 0.2)
        self.assertEqual(scores["trigger_accuracy"], 0.75)
        self.assertIsNone(scores["fixture_accuracy"])

    def test_gate_reports_breaches_and_skips_unmeasured(self):
        by_lang = {"en": {"pass_rate": 1.0, "variant_overlap": 0.4, "fixture_accuracy": None}}
        gate = run_evals.apply_gate(by_lang, {"min_pass_rate": 1.0, "max_variant_overlap": 0.35,
                                              "min_fixture_accuracy": 1.0})
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["failures"],
                         [{"lang": "en", "score": "variant_overlap", "value": 0.4, "max": 0.35}])

    def test_gate_rejects_unknown_threshold(self):
        with self.assertRaises(RuntimeError):
            run_evals.apply_gate({"en": {"pass_rate": 1.0}}, {"min_vibes": 1.0})

    def test_thresholds_file_names_real_scores(self):
        scores = run_evals.score_language([])
        for key in run_evals.load_thresholds():
            bound, _, name = key.partition("_")
            self.assertIn(bound, ("min", "max"), key)
            self.assertIn(name, scores, key)

    def test_failed_gate_fails_the_run(self):
        code, report = run_evals.run_evals(cases_dir=CASES_DIR, quiet=True,
                                           thresholds={"max_variant_overlap": 0.0})
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertFalse(report["gate"]["ok"])


class EvalRunnerTest(unittest.TestCase):
    """Verify evaluation runner execution and output formatting."""

    def test_eval_runner_api(self):
        code, report = run_evals.run_evals(cases_dir=CASES_DIR, quiet=True)
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["total"], 30)
        self.assertEqual(report["passed"], report["total"])
        self.assertEqual(report["pass_rate"], 1.0)
        self.assertTrue(report["gate"]["ok"], report["gate"]["failures"])
        for lang_code in ("en", "vi", "ja"):
            self.assertIn(lang_code, report["by_lang"])
            self.assertEqual(report["by_lang"][lang_code]["pass_rate"], 1.0)

    def test_unwritable_report_path_fails(self):
        proc = subprocess.run([sys.executable, str(RUNNER), "--quiet", "--json", str(CASES_DIR)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error:", proc.stderr)

    def test_eval_runner_cli(self):
        proc = subprocess.run([sys.executable, str(RUNNER)], capture_output=True,
                              text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("EVALUATION SUMMARY", proc.stdout)
        self.assertIn("Language Breakdown", proc.stdout)
        self.assertIn("Gate: PASS", proc.stdout)
        self.assertIn("en:", proc.stdout)
        self.assertIn("vi:", proc.stdout)
        self.assertIn("ja:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
