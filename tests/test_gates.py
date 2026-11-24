"""Tests for configurable passes and gates, presets, resolutions, and the final floor (story 026)."""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from _nli import judge_all
from paraphrase_everything import harness

PE = Path(_path.SCRIPTS) / "pe.py"
SKILL_DIR = Path(_path.SCRIPTS).parent
CASES = {
    "en": {"original": "In 2024 the team had 42 members. They did not miss a deadline.",
           "facts": [{"id": "f1", "fact": "The team had 42 members in 2024", "anchors": ["42", "2024"]}],
           "good": "The team counted 42 members in 2024. They never missed a deadline.",
           "bad_number": "The team counted 40 members in 2024. They never missed a deadline."},
    "vi": {"original": "Năm 2023, công ty tuyển 15 kỹ sư. Họ không làm việc vào cuối tuần.",
           "facts": [{"id": "f1", "fact": "Công ty tuyển 15 kỹ sư năm 2023", "anchors": ["15", "2023"]}],
           "good": "Công ty đã tuyển 15 kỹ sư trong năm 2023. Họ nghỉ vào cuối tuần.",
           "bad_number": "Công ty đã tuyển 51 kỹ sư trong năm 2023. Họ nghỉ vào cuối tuần."},
    "ja": {"original": "新工場は2026年に稼働し、300人を雇用する。残業は認めない。",
           "facts": [{"id": "f1", "fact": "新工場は2026年に稼働し300人を雇用する", "anchors": ["2026", "300"]}],
           "good": "2026年に操業を始める新工場では、300人が雇用される。残業は禁止だ。",
           "bad_number": "2026年に操業を始める新工場では、200人が雇用される。残業は禁止だ。"},
}


def types(issues):
    """The set of issue types."""
    return {i["type"] for i in issues}


class ParseTest(unittest.TestCase):
    def test_parse_gates(self):
        self.assertEqual(harness.parse_gates("1, 3,5"), ["g1", "g3", "g5"])
        self.assertEqual(harness.parse_gates("g5,g2"), ["g2", "g5"])
        self.assertEqual(harness.parse_gates(""), [])
        self.assertEqual(harness.parse_gates(None), harness.GATES)
        for bad in ("6", "g0", "x"):
            with self.assertRaises(harness.HarnessError):
                harness.parse_gates(bad)

    def test_resolutions_are_deterministic(self):
        everything = [p["id"] for p in harness.PASSES]
        self.assertEqual(harness.resolve(everything, harness.GATES), (harness.GATES, [], []))
        active, skipped, res = harness.resolve(["analysis", "plan", "style"], [])
        self.assertEqual((active, skipped), (["g1", "g2"], ["g3", "g4", "g5"]))
        self.assertEqual([(r["gate"], r["action"]) for r in res], [("g1", "kept"), ("g2", "kept"), ("g5", "floor")])
        active, skipped, res = harness.resolve(["structure", "style"], ["g2", "g3", "g5"])
        self.assertEqual(active, ["g3", "g5"])
        self.assertEqual([(r.get("gate", r.get("check")), r["action"]) for r in res],
                         [("g2", "dropped"), ("entailment", "aligner")])
        self.assertEqual(harness.resolve(["structure", "style"], ["g2", "g3", "g5"])[2], res)

    def test_presets_resolve_to_their_config(self):
        expected = {"fast": (["style"], [], "self"),
                    "standard": (["plan", "lexis", "style"], ["g2", "g4", "g5"], "self"),
                    "strict": ([p["id"] for p in harness.PASSES], harness.GATES, "independent")}
        for name, (passes, gates, judge) in expected.items():
            with self.subTest(preset=name), tempfile.TemporaryDirectory() as tmp:
                state = harness.init("One sentence here.", Path(tmp) / "s", preset=name)
                self.assertEqual((state["passes"], state["gates"], state["judge"]), (passes, gates, judge))
                self.assertEqual(state["preset"], name)

    def test_flags_override_the_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = harness.init("One sentence here.", Path(tmp) / "s", preset="strict", gates="")
            self.assertEqual(state["passes"], [p["id"] for p in harness.PASSES])
            self.assertEqual(state["gates"], ["g1", "g2"])  # JSON pass gates are kept
            state = harness.init("One sentence here.", Path(tmp) / "t", preset="fast", passes="plan,style")
            self.assertEqual((state["passes"], state["gates"]), (["plan", "style"], ["g2"]))

    def test_unknown_preset(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(harness.HarnessError):
            harness.init("One sentence here.", Path(tmp) / "s", preset="turbo")


class FloorTest(unittest.TestCase):
    """The final floor check runs in every configuration, including ``--gates ""``."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, session, name, data):
        """Write a JSON or text file into ``session``."""
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        (session / name).write_text(text, encoding="utf-8")

    def test_floor_with_every_gate_disabled_every_language(self):
        for code, case in CASES.items():
            with self.subTest(code=code):
                session = self.root / code
                harness.init(case["original"], session, lang_code=code, passes="analysis,style", gates="")
                self.write(session, "analysis.json", {"facts": case["facts"]})
                self.assertTrue(harness.submit(session)["ok"])  # g1 kept: the floor needs the facts
                task = harness.next_task(session)
                self.assertEqual(task["checks"], "floor")
                self.assertNotIn("entailment", task)
                self.assertEqual(task["review_required"], ["verdicts: one per fact in state.facts"])
                self.write(session, "p5-style.txt", case["bad_number"])
                found = types(harness.submit(session)["issues"])
                self.assertTrue({"number_missing", "anchor_missing", "verdict_missing"} <= found, found)
                self.write(session, "p5-style.txt", case["good"])
                self.write(session, "p5-style.review.json", {"verdicts": [{"id": "f1", "verdict": "kept"}]})
                result = harness.submit(session)
                self.assertTrue(result["ok"], result["issues"])  # no entailment file, warnings ignored
                report = harness.write_report(session)
                self.assertEqual([g["gate"] for g in report["gates_run"]], ["g1", "floor", "floor"])
                self.assertEqual(report["gates_skipped"], ["g2", "g3", "g4", "g5"])
                self.assertIn("entailment", report["skipped_checks"])
                self.assertNotIn("key facts", report["skipped_checks"])

    def test_floor_catches_placeholders_and_protected_spans(self):
        session = self.root / "p"
        harness.init("Run `make test` before you push.", session, passes="style", gates="")
        self.write(session, "p5-style.txt", "Run the tests before you push.")
        self.assertTrue({"placeholder_missing", "protected_span_missing"} <= types(harness.submit(session)["issues"]))
        self.write(session, "p5-style.txt", "Before you push, run ⟦P1⟧.")
        self.assertTrue(harness.submit(session)["ok"])
        self.assertEqual((session / "output.txt").read_text(encoding="utf-8"), "Before you push, run `make test`.")

    def test_fast_preset_reports_what_it_skips(self):
        session = self.root / "f"
        harness.init("It is not uncommon for builds to fail.", session, preset="fast")
        self.write(session, "p5-style.txt", "Builds commonly fail.")
        self.assertTrue(harness.submit(session)["ok"])  # the negation warning is not a floor check
        report = harness.write_report(session)
        self.assertEqual(report["preset"], "fast")
        self.assertEqual(report["skipped_checks"],
                         ["key facts", "plan adherence", "check warnings", "length target", "entailment"])
        self.assertEqual([r["action"] for r in report["resolutions"]], ["floor"])
        self.assertIsNone(report["entailment"])

    def test_skipped_middle_gate_passes_through(self):
        case = CASES["en"]
        session = self.root / "m"
        harness.init(case["original"], session, passes="lexis,style", gates="5")
        self.assertEqual(harness.next_task(session)["checks"], "skipped")
        self.write(session, "p4-lexis.txt", case["bad_number"])
        result = harness.submit(session)
        self.assertEqual((result["ok"], result["next"]), (True, "style"))
        self.write(session, "p5-style.txt", case["bad_number"])
        judge_all(session)
        self.assertIn("number_missing", types(harness.submit(session)["issues"]))
        self.write(session, "p5-style.txt", case["good"])
        judge_all(session)
        self.assertTrue(harness.submit(session)["ok"])
        report = harness.write_report(session)
        self.assertEqual([g["gate"] for g in report["gates_run"]], ["g5", "g5"])
        self.assertEqual(report["gates_skipped"], ["g1", "g2", "g3", "g4"])
        self.assertIn("lexis gate", report["skipped_checks"])

    def test_strict_recommends_an_independent_judge(self):
        session = self.root / "s"
        harness.init(CASES["en"]["original"], session, preset="strict", passes="style")
        self.assertEqual(harness.next_task(session)["entailment"]["judge_recommended"], "independent")


class CliTest(unittest.TestCase):
    def pe(self, *args):
        """Run ``pe`` in a new process; return (exit code, JSON output)."""
        proc = subprocess.run([sys.executable, str(PE), *args], capture_output=True, text=True,
                              encoding="utf-8", input="")
        return proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else proc.stderr

    def test_flags_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "in.txt"
            source.write_text("One sentence here.", encoding="utf-8")
            self.assertEqual(self.pe("run", "init", str(source), "-o", str(Path(tmp) / "a"), "--gates", "9")[0], 2)
            self.assertEqual(self.pe("run", "init", str(source), "-o", str(Path(tmp) / "b"), "--preset", "x")[0], 2)
            self.assertEqual(self.pe("run", "next", str(Path(tmp) / "a"), "--gates", "1")[0], 2)
            code, out = self.pe("run", "init", str(source), "-o", str(Path(tmp) / "c"), "--gates", "",
                                "--passes", "plan,style")
            self.assertEqual((code, out["gates"]), (0, ["g2"]))
            self.assertEqual([r["action"] for r in out["resolutions"]], ["kept", "floor"])


class PresetDocTest(unittest.TestCase):
    def test_presets_md_matches_presets_json(self):
        doc = (SKILL_DIR / "references" / "presets.md").read_text(encoding="utf-8")
        rows = {m.group(1): [c.strip() for c in m.group(2).split("|")]
                for m in re.finditer(r"^\| `(\w+)` \|(.+)\|$", doc, re.M)}
        presets = harness.presets()
        self.assertEqual(set(rows), set(presets))
        for name, cfg in presets.items():
            passes, gates, judge = rows[name][:3]
            self.assertEqual(passes, ", ".join(cfg["passes"]), name)
            self.assertEqual(gates, ", ".join(cfg["gates"]) or "none", name)
            self.assertEqual(judge, cfg["judge"], name)


if __name__ == "__main__":
    unittest.main()
