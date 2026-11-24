"""Tests for the session harness (story 022): happy path, rewind, round exhaustion, tampering."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import harness

PE = Path(_path.SCRIPTS) / "pe.py"

CASES = {
    "en": {"original": "In 2024 the team had 42 members. They did not miss a deadline.",
           "facts": [{"id": "f1", "fact": "The team had 42 members in 2024", "anchors": ["42", "2024"]}],
           "good": "The team counted 42 members in 2024. They never missed a deadline.",
           "bad_number": "The team counted 40 members in 2024. They never missed a deadline."},
    "vi": {"original": "Năm 2023, công ty tuyển 15 kỹ sư. Họ không làm việc vào cuối tuần.",
           "facts": [{"id": "f1", "fact": "Công ty tuyển 15 kỹ sư năm 2023", "anchors": ["15", "2023"]}],
           "good": "Công ty đã tuyển 15 kỹ sư trong năm 2023. Họ không đi làm vào cuối tuần.",
           "bad_number": "Công ty đã tuyển 51 kỹ sư trong năm 2023. Họ không đi làm vào cuối tuần."},
    "ja": {"original": "新工場は2026年に稼働し、300人を雇用する。残業は認めない。",
           "facts": [{"id": "f1", "fact": "新工場は2026年に稼働し300人を雇用する", "anchors": ["2026", "300"]}],
           "good": "2026年に操業を始める新工場では、300人が雇用される。残業は認めない。",
           "bad_number": "2026年に操業を始める新工場では、200人が雇用される。残業は認めない。"},
}


class SessionTest(unittest.TestCase):
    """Library-level tests against a fresh temporary session."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "session"

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, code="en", **kwargs):
        """Init a session for the language case ``code`` (analysis and style unless given)."""
        kwargs.setdefault("passes", "analysis,style")
        harness.init(CASES[code]["original"], self.dir, lang_code=code, **kwargs)
        return CASES[code]

    def write(self, name, content):
        """Write an artifact (JSON for non-strings) into the session directory."""
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        (self.dir / name).write_text(text, encoding="utf-8")

    def analyse(self, case):
        """Complete pass 1 with the case's facts."""
        self.write("analysis.json", {"facts": case["facts"]})
        self.assertTrue(harness.submit(self.dir)["ok"])

    def kept(self, case):
        """A review file that marks every fact as kept."""
        return {"verdicts": [{"id": f["id"], "verdict": "kept"} for f in case["facts"]]}

    def test_happy_path_every_language(self):
        for code in CASES:
            with self.subTest(code=code):
                self.dir = Path(self.tmp.name) / code
                case = self.start(code, passes="analysis,plan,style")
                task = harness.next_task(self.dir)
                self.assertEqual((task["step"], task["gate"], task["pass"]), ("analysis", "g1", "1/3"))
                self.assertEqual([s["id"] for s in task["sentences"]], [1, 2])
                self.analyse(case)
                task = harness.next_task(self.dir)
                self.assertEqual((task["step"], task["gate"]), ("plan", "g2"))
                self.assertEqual(task["state"]["analysis"], {"facts": case["facts"]})
                self.write("plan.json", {"rows": [{"src": [1], "ops": ["lexical"], "target": 1},
                                                  {"src": [2], "ops": ["clause"], "target": 1}]})
                result = harness.submit(self.dir)
                self.assertTrue(result["ok"], result["issues"])
                task = harness.next_task(self.dir)
                self.assertEqual(task["step"], "style")
                self.assertEqual(task["state"]["facts"], case["facts"])
                self.assertIn("review_required", task)
                self.assertTrue(any(p.endswith(f"{code}.md") for p in task["instructions"]))
                self.write("p5-style.txt", case["good"])
                self.write("p5-style.review.json", self.kept(case))
                result = harness.submit(self.dir)
                self.assertTrue(result["ok"], result["issues"])
                self.assertEqual(result["status"], "complete")
                self.assertEqual(harness.next_task(self.dir)["step"], "done")
                report = json.loads((self.dir / harness.REPORT_FILE).read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "complete")
                self.assertEqual(report["passes_run"], ["analysis", "plan", "style"])
                self.assertEqual(report["gates_skipped"], ["g3", "g4"])
                self.assertEqual(report["open_issues"], [])
                self.assertTrue(report["output"].endswith("output.txt"))
                self.assertEqual((self.dir / "output.txt").read_text(encoding="utf-8"), case["good"])

    def test_next_is_idempotent_and_single(self):
        self.start()
        first, second = harness.next_task(self.dir), harness.next_task(self.dir)
        self.assertEqual(first, second)
        self.assertIsInstance(first["step"], str)

    def test_failed_gate_returns_same_pass_with_issues(self):
        case = self.start("vi")
        self.analyse(case)
        self.write("p5-style.txt", case["bad_number"])
        self.write("p5-style.review.json", self.kept(case))
        result = harness.submit(self.dir)
        self.assertFalse(result["ok"])
        self.assertEqual((result["status"], result["next"]), ("in_progress", "style"))
        task = harness.next_task(self.dir)
        self.assertEqual(task["round"], 1)
        types = {i["type"] for i in task["issues"]}
        self.assertTrue({"number_missing", "number_extra", "anchor_missing"} <= types, types)
        self.write("p5-style.txt", case["good"])
        self.assertTrue(harness.submit(self.dir)["ok"])

    def test_round_exhaustion_ends_incomplete(self):
        case = self.start("ja", max_rounds=1)
        self.analyse(case)
        self.write("p5-style.txt", case["bad_number"])
        self.assertEqual(harness.submit(self.dir)["status"], "in_progress")
        result = harness.submit(self.dir)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(harness.status(self.dir)["rounds"]["style"], 1)
        task = harness.next_task(self.dir)
        self.assertEqual(task["step"], "incomplete")
        report = json.loads((self.dir / harness.REPORT_FILE).read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "incomplete")
        self.assertIsNone(report["output"])
        self.assertTrue(any(i["type"] == "number_missing" and i["gate"] == "g5" for i in report["open_issues"]))
        with self.assertRaises(harness.HarnessError):
            harness.submit(self.dir)

    def test_missing_verdicts_fail_last_gate(self):
        case = self.start()
        self.analyse(case)
        self.write("p5-style.txt", case["good"])
        issues = harness.submit(self.dir)["issues"]
        self.assertEqual(issues, [{"type": "verdict_missing", "id": "f1"}])

    def test_accepted_warning_is_reported(self):
        harness.init("It is not uncommon for builds to fail.", self.dir, passes="style")
        self.write("p5-style.txt", "Builds commonly fail.")
        result = harness.submit(self.dir)
        self.assertEqual([i["type"] for i in result["issues"]], ["negation_mismatch"])
        self.write("p5-style.review.json", {"accept": [{"id": "w1", "reason": "double negative made positive"}]})
        self.assertTrue(harness.submit(self.dir)["ok"])
        report = harness.write_report(self.dir)
        self.assertEqual(report["accepted_warnings"][0]["reason"], "double negative made positive")
        self.assertFalse(report["facts_frozen"])
        self.assertEqual(report["gates_skipped"], ["g1", "g2", "g3", "g4"])

    def test_invalid_artifacts_fail_the_gate(self):
        self.start()
        self.write("analysis.json", "{not json")
        self.assertEqual(harness.submit(self.dir)["issues"][0]["type"], "invalid_artifact")
        self.write("analysis.json", {"facts": [{"id": "f1", "fact": "x", "anchors": ["999"]}]})
        self.assertEqual(harness.submit(self.dir)["issues"][0]["type"], "anchor_not_in_original")

    def test_missing_artifact_is_a_usage_error(self):
        self.start()
        with self.assertRaises(harness.HarnessError):
            harness.submit(self.dir)

    def test_original_tampering(self):
        self.start()
        (self.dir / harness.ORIGINAL_FILE).write_text("Something else.", encoding="utf-8")
        for call in (harness.next_task, harness.submit, harness.status, harness.write_report):
            with self.assertRaises(harness.HarnessError):
                call(self.dir)
        with self.assertRaises(harness.HarnessError):
            harness.rewind(self.dir, "analysis")

    def test_analysis_is_frozen_until_rewind(self):
        case = self.start()
        self.analyse(case)
        self.assertEqual(harness.status(self.dir)["frozen"], ["analysis.json"])
        self.write("analysis.json", {"facts": case["facts"] + [{"id": "f2", "fact": "y", "anchors": []}]})
        with self.assertRaises(harness.HarnessError):
            harness.next_task(self.dir)

    def test_rewind_to_analysis_invalidates_later_passes(self):
        case = self.start()
        self.analyse(case)
        self.write("p5-style.txt", case["good"])
        self.write("p5-style.review.json", self.kept(case))
        harness.submit(self.dir)
        result = harness.rewind(self.dir, "analysis")
        self.assertEqual(result["invalidated"], ["analysis", "style"])
        for name in ("analysis.json", "p5-style.txt", "p5-style.review.json", harness.REPORT_FILE):
            self.assertFalse((self.dir / name).exists(), name)
        state = harness.status(self.dir)
        self.assertEqual((state["status"], state["current"], state["frozen"]), ("in_progress", "analysis", []))
        self.assertTrue(all(h["invalidated"] for h in state["history"]))
        self.assertNotIn("state", harness.next_task(self.dir))
        self.analyse(case)

    def test_rewind_rejects_unknown_and_forward(self):
        self.start()
        with self.assertRaises(harness.HarnessError):
            harness.rewind(self.dir, "plan")
        with self.assertRaises(harness.HarnessError):
            harness.rewind(self.dir, "style")

    def test_init_validation(self):
        bad = [dict(mode="loud"), dict(persona="pirate"), dict(passes="analysis"),
               dict(passes="style,colour"), dict(passes=""), dict(max_rounds=-1)]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(harness.HarnessError):
                harness.init("Some text.", Path(self.tmp.name) / "x", **kwargs)
        harness.init("Some text.", self.dir)
        with self.assertRaises(harness.HarnessError):
            harness.init("Some text.", self.dir)

    def test_persona_reference_is_loaded(self):
        harness.init("Please send the file.", self.dir, passes="style", persona="formal")
        task = harness.next_task(self.dir)
        self.assertTrue(any(p.endswith("formal.md") for p in task["instructions"]))
        self.assertEqual(task["constraints"]["persona"], "formal")
        self.assertEqual(task["merged_passes"], ["structure", "lexis"])
        self.assertEqual(len(task["duties"]), 3)

    def test_protected_spans_listed(self):
        harness.init("Run `make test` and see https://example.com today.", self.dir)
        self.assertEqual(harness.next_task(self.dir)["constraints"]["protected"],
                         ["`make test`", "https://example.com"])


class CliTest(unittest.TestCase):
    """The ``pe run`` CLI: exit codes and state that survives separate processes."""

    def pe(self, *args):
        """Run ``pe`` in a new process; return (exit code, JSON output)."""
        proc = subprocess.run([sys.executable, str(PE), *args], capture_output=True, text=True, encoding="utf-8",
                              input="")
        return proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else proc.stderr

    def test_full_session_across_processes(self):
        case = CASES["en"]
        with tempfile.TemporaryDirectory() as tmp:
            source, session = Path(tmp) / "in.txt", Path(tmp) / "s"
            source.write_text(case["original"], encoding="utf-8")
            code, out = self.pe("run", "init", str(source), "-o", str(session), "--mode", "standard",
                                "--passes", "analysis,style")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["current"], "analysis")
            self.assertEqual(self.pe("run", "submit", str(session))[0], 2)  # no artifact yet
            (session / "analysis.json").write_text(json.dumps({"facts": case["facts"]}), encoding="utf-8")
            self.assertEqual(self.pe("run", "submit", str(session))[0], 0)
            (session / "p5-style.txt").write_text(case["bad_number"], encoding="utf-8")
            self.assertEqual(self.pe("run", "submit", str(session))[0], 1)
            code, status = self.pe("run", "status", str(session))
            self.assertEqual((code, status["current"], status["rounds"]["style"]), (0, "style", 1))
            (session / "p5-style.txt").write_text(case["good"], encoding="utf-8")
            (session / "p5-style.review.json").write_text(
                json.dumps({"verdicts": [{"id": "f1", "verdict": "kept"}]}), encoding="utf-8")
            self.assertEqual(self.pe("run", "submit", str(session))[0], 0)
            code, report = self.pe("run", "report", str(session))
            self.assertEqual((code, report["status"]), (0, "complete"))
            self.assertEqual(self.pe("run", "next", str(session))[1]["step"], "done")

    def test_default_session_dir_and_errors(self):
        code, out = self.pe("run", "init", "-", "--passes", "style")
        self.assertEqual(code, 2)  # empty stdin
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "in.txt"
            source.write_text("Hello there, friend.", encoding="utf-8")
            code, out = self.pe("run", "init", str(source))
            self.assertEqual(code, 0)
            session = Path(out["session"])
            try:
                self.assertTrue((session / harness.SESSION_FILE).is_file())
                self.assertEqual(self.pe("run", "rewind", str(session))[0], 2)  # needs --to
                code, err = self.pe("run", "next", str(session), "--mode", "light")
                self.assertEqual(code, 2)
                self.assertIn("does not take --mode", err["error"])
            finally:
                for path in sorted(session.rglob("*"), reverse=True):
                    path.rmdir() if path.is_dir() else path.unlink()
                session.rmdir()
        self.assertEqual(self.pe("run", "status", tmp)[0], 2)  # not a session


if __name__ == "__main__":
    unittest.main()
