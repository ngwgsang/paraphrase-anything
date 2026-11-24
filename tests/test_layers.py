"""Tests for passes 3–5: layered rewriting, their gates, merging, and placeholders (story 024)."""

import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from _nli import judge_all
from paraphrase_everything import harness, planning

PLAN = {"rows": [{"src": [1], "ops": ["split", "voice"], "target": 2},
                 {"src": [2], "ops": ["keep"], "target": 1}]}
CASES = {
    "en": {"original": "The report was written by the team, and it was published in March. Sales rose by 5%.",
           "facts": [{"id": "f1", "fact": "Sales rose by 5%", "anchors": ["5%"]}],
           "structure": "The report was written by the team. It was published in March. Sales rose by 5%.",
           "lexis": "The team wrote the report. It came out in March. Sales rose by 5%."},
    "vi": {"original": "Báo cáo được nhóm nghiên cứu viết và công bố vào tháng 3. Doanh thu tăng 5%.",
           "facts": [{"id": "f1", "fact": "Doanh thu tăng 5%", "anchors": ["5%"]}],
           "structure": "Báo cáo được nhóm nghiên cứu viết. Báo cáo được công bố vào tháng 3. Doanh thu tăng 5%.",
           "lexis": "Nhóm nghiên cứu đã viết báo cáo. Báo cáo ra mắt vào tháng 3. Doanh thu tăng 5%."},
    "ja": {"original": "報告書はチームによって作成され、3月に公開された。売上は5%増えた。",
           "facts": [{"id": "f1", "fact": "売上は5%増えた", "anchors": ["5%"]}],
           "structure": "報告書はチームによって作成された。3月に公開された。売上は5%増えた。",
           "lexis": "チームが報告書を作成した。3月に公表された。売上は5%増えた。"},
}


def types(issues):
    """The set of issue types."""
    return {i["type"] for i in issues}


class LayeredSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "s"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        """Write a JSON or text artifact into the session."""
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        (self.dir / name).write_text(text, encoding="utf-8")

    def submit(self, name, data):
        """Write an artifact and submit it; return the submit result."""
        self.write(name, data)
        return harness.submit(self.dir)

    def final(self, name, data):
        """Write the last pass's artifact, judge its entailment pairs, and submit it."""
        self.write(name, data)
        judge_all(self.dir)
        return harness.submit(self.dir)

    def through_plan(self, case, plan=PLAN, **kwargs):
        """Init a five-pass session and pass gates 1 and 2."""
        harness.init(case["original"], self.dir, **kwargs)
        self.assertTrue(self.submit("analysis.json", {"facts": case["facts"]})["ok"])
        result = self.submit("plan.json", plan)
        self.assertTrue(result["ok"], result["issues"])

    def test_full_layered_session_every_language(self):
        for code, case in CASES.items():
            with self.subTest(code=code):
                self.dir = Path(self.tmp.name) / code
                self.through_plan(case, lang_code=code)
                task = harness.next_task(self.dir)
                self.assertEqual((task["step"], task["gate"], task["pass"]), ("structure", "g3", "3/5"))
                self.assertEqual(task["ops"], ["split", "merge", "reorder"])
                self.assertEqual(task["plan"], [{"row": 1, "src": [1], "ops": ["split"], "target": 2},
                                                {"row": 2, "src": [2], "ops": ["keep"], "target": 1}])
                self.assertEqual([Path(p).name for p in task["instructions"]], ["layers.md"])
                self.assertTrue(task["inputs"]["previous"].endswith("masked.txt"))
                result = self.submit("p3-structure.txt", case["structure"])
                self.assertTrue(result["ok"], result["issues"])

                task = harness.next_task(self.dir)
                self.assertEqual(task["step"], "lexis")
                self.assertEqual(task["plan"][0]["ops"], ["voice"])
                self.assertTrue(task["inputs"]["previous"].endswith("p3-structure.txt"))
                self.assertEqual([Path(p).name for p in task["instructions"]], ["layers.md", f"{code}.md"])
                result = self.submit("p4-lexis.txt", case["lexis"])
                self.assertTrue(result["ok"], result["issues"])

                task = harness.next_task(self.dir)
                self.assertEqual((task["step"], task["ops"]), ("style", ["register", "shorten", "expand"]))
                self.assertEqual(task["plan"][0]["ops"], [])
                self.write("p5-style.review.json", {"verdicts": [{"id": "f1", "verdict": "kept"}]})
                result = self.final("p5-style.txt", case["lexis"])
                self.assertTrue(result["ok"], result["issues"])
                report = harness.write_report(self.dir)
                self.assertEqual(report["passes_run"], ["analysis", "plan", "structure", "lexis", "style"])
                self.assertEqual(report["gates_skipped"], [])
                self.assertEqual((self.dir / "output.txt").read_text(encoding="utf-8"), case["lexis"])

    def test_gate_3_split_row_must_split(self):
        case = CASES["en"]
        self.through_plan(case)
        result = self.submit("p3-structure.txt", case["original"])
        self.assertEqual([(i["type"], i["row"], i["expected"], i["got"]) for i in result["issues"]],
                         [("plan_target_mismatch", 1, 2, 1)])

    def test_gate_3_keep_row_must_not_change(self):
        case = CASES["vi"]
        self.through_plan(case, lang_code="vi")
        changed = case["structure"].replace("Doanh thu tăng 5%.", "Doanh số tăng 5%.")
        self.assertEqual(types(self.submit("p3-structure.txt", changed)["issues"]), {"keep_row_changed"})

    def test_gate_3_checks_frozen_anchors_without_verdicts(self):
        case = CASES["ja"]
        self.through_plan(case, lang_code="ja")
        lost = case["structure"].replace("5%", "6%")
        found = types(self.submit("p3-structure.txt", lost)["issues"])
        self.assertIn("anchor_missing", found)
        self.assertNotIn("verdict_missing", found)

    def test_gate_4_sentence_count_must_not_change(self):
        case = CASES["en"]
        self.through_plan(case)
        self.submit("p3-structure.txt", case["structure"])
        merged = "The team wrote the report, which came out in March. Sales rose by 5%."
        result = self.submit("p4-lexis.txt", merged)
        self.assertEqual([(i["type"], i["expected"], i["got"]) for i in result["issues"]],
                         [("sentence_count_changed", 3, 2)])

    def test_merged_passes_take_the_union_of_ops(self):
        case = CASES["en"]
        harness.init(case["original"], self.dir, passes="plan,style")
        self.submit("plan.json", PLAN)
        task = harness.next_task(self.dir)
        self.assertEqual(task["merged_passes"], ["structure", "lexis"])
        self.assertEqual(task["ops"], ["split", "merge", "reorder", "voice", "clause", "lexical",
                                       "register", "shorten", "expand"])
        self.assertEqual(task["plan"][0]["ops"], ["split", "voice"])
        self.assertEqual(len(task["duties"]), 3)
        self.assertEqual(types(self.final("p5-style.txt", case["original"])["issues"]), {"plan_target_mismatch"})
        self.assertTrue(self.final("p5-style.txt", case["lexis"])["ok"])
        report = harness.write_report(self.dir)
        self.assertEqual([g["gate"] for g in report["gates_run"]], ["g2", "g5", "g5"])
        self.assertEqual(report["gates_skipped"], ["g1", "g3", "g4"])

    def test_structure_merged_into_lexis(self):
        case = CASES["en"]
        harness.init(case["original"], self.dir, passes="plan,lexis,style")
        self.submit("plan.json", PLAN)
        task = harness.next_task(self.dir)
        self.assertEqual((task["step"], task["merged_passes"]), ("lexis", ["structure"]))
        self.assertEqual(types(self.submit("p4-lexis.txt", case["original"])["issues"]), {"plan_target_mismatch"})
        self.assertTrue(self.submit("p4-lexis.txt", case["lexis"])["ok"])
        self.assertTrue(self.final("p5-style.txt", case["lexis"])["ok"])

    def test_drop_rows_count_once_until_the_shorten_pass(self):
        original = "Revenue rose 12% this year. This is a very pleasing result for everyone involved."
        plan = {"rows": [{"src": [1], "ops": ["lexical"], "target": 1},
                         {"src": [2], "ops": ["shorten"], "target": 0}]}
        harness.init(original, self.dir, mode="shorten", passes="plan,structure,lexis,style")
        self.assertTrue(self.submit("plan.json", plan)["ok"])
        self.assertEqual(harness.next_task(self.dir)["plan"][1]["target"], 1)
        self.assertTrue(self.submit("p3-structure.txt", original)["ok"])
        lexis = "Revenue grew 12% this year. This is a very pleasing result for everyone involved."
        self.assertTrue(self.submit("p4-lexis.txt", lexis)["ok"])
        self.assertEqual(harness.next_task(self.dir)["plan"][1]["target"], 0)
        self.assertEqual(types(self.final("p5-style.txt", lexis)["issues"]), {"plan_target_mismatch"})
        result = self.final("p5-style.txt", "Revenue grew 12% this year.")
        self.assertEqual(types(result["issues"]), {"sentence_unaligned"})  # check still flags the drop
        self.write("p5-style.review.json", {"accept": [{"id": "w1", "reason": "planned drop in shorten mode"}]})
        self.assertTrue(harness.submit(self.dir)["ok"])

    def test_placeholders_must_survive_every_pass(self):
        original = "Run `make test` before you push. Then open https://example.com/ci to watch the build."
        plan = {"rows": [{"src": [1, 2], "ops": ["merge"], "target": 1}]}
        harness.init(original, self.dir, passes="plan,structure,style")
        self.submit("plan.json", plan)
        task = harness.next_task(self.dir)
        self.assertEqual(task["constraints"]["placeholders"], ["⟦P1⟧", "⟦P2⟧"])
        masked = (self.dir / "masked.txt").read_text(encoding="utf-8")
        self.assertEqual(masked, "Run ⟦P1⟧ before you push. Then open ⟦P2⟧ to watch the build.")
        good = "Run ⟦P1⟧ before you push, then open ⟦P2⟧ to watch the build."
        self.assertIn("placeholder_missing", types(self.submit("p3-structure.txt", good.replace("⟦P2⟧", "the CI page"))["issues"]))
        self.assertIn("placeholder_duplicated", types(self.submit("p3-structure.txt", good + " ⟦P1⟧")["issues"]))
        self.assertTrue(self.submit("p3-structure.txt", good)["ok"])
        self.assertTrue(harness.next_task(self.dir)["inputs"]["previous"].endswith("p3-structure.txt"))
        self.assertIn("placeholder_unknown", types(self.final("p5-style.txt", good + " ⟦P9⟧")["issues"]))
        self.assertTrue(self.final("p5-style.txt", good)["ok"])
        self.assertEqual((self.dir / "output.txt").read_text(encoding="utf-8"),
                         "Run `make test` before you push, then open https://example.com/ci to watch the build.")

    def test_plan_is_frozen_after_gate_2(self):
        case = CASES["en"]
        self.through_plan(case)
        self.assertEqual(harness.status(self.dir)["frozen"], ["analysis.json", "plan.json"])
        self.write("plan.json", {"rows": [{"src": [1, 2], "ops": ["merge"], "target": 1}]})
        with self.assertRaises(harness.HarnessError):
            harness.next_task(self.dir)
        self.write("plan.json", PLAN)  # same bytes as the frozen file: accepted again
        self.assertEqual(harness.next_task(self.dir)["step"], "structure")

    def test_rewind_to_plan_keeps_analysis(self):
        case = CASES["en"]
        self.through_plan(case)
        self.submit("p3-structure.txt", case["structure"])
        harness.rewind(self.dir, "plan")
        state = harness.status(self.dir)
        self.assertEqual((state["current"], state["frozen"]), ("plan", ["analysis.json"]))
        self.assertFalse((self.dir / "p3-structure.txt").exists())
        self.assertFalse((self.dir / "masked.txt").exists())

    def test_placeholder_like_input_is_rejected(self):
        with self.assertRaises(harness.HarnessError):
            harness.init("Text with ⟦P1⟧ already.", self.dir)


class SegmentTest(unittest.TestCase):
    """The plan-ordered segmentation behind plan adherence."""

    def test_reorder_and_split(self):
        original = "The bridge closed in May and traffic rose. Route 9 was busy. Buses ran late."
        plan = {"rows": [{"src": [2], "ops": ["reorder"], "target": 1},
                         {"src": [1], "ops": ["split"], "target": 2},
                         {"src": [3], "ops": ["keep"], "target": 1}]}
        rewrite = "Route 9 was busy. The bridge closed in May. Traffic rose. Buses ran late."
        self.assertEqual(planning.adherence(plan, original, rewrite, "en"), [])

    def test_too_many_sentences(self):
        plan = {"rows": [{"src": [1], "ops": ["keep"], "target": 1}]}
        rewrite = " ".join(["One."] * 8)
        self.assertEqual(planning.adherence(plan, "One.", rewrite, "en"),
                         [{"type": "plan_sentence_count", "expected": 1, "got": 8}])


if __name__ == "__main__":
    unittest.main()
