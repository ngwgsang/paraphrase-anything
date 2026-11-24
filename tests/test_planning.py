"""Tests for passes 1–2: analysis and plan validators, and their harness gates (story 023)."""

import json
import re
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import harness, planning

REFERENCES = Path(_path.SCRIPTS).parent / "references"

EN = "The bridge closed in May. Because of that, traffic doubled on Route 9."
VI = "Nếu trời mưa, buổi hòa nhạc sẽ dời sang thứ Bảy. Vé đã bán vẫn có hiệu lực."
JA = "売上は20%増えた。しかし、利益は減少した。"


def types(errors):
    """The set of issue types in an error list."""
    return {e["type"] for e in errors}


class SentencesTest(unittest.TestCase):
    def test_ids_follow_the_check_splitter(self):
        self.assertEqual(planning.sentences(EN, "en"),
                         [{"id": 1, "text": "The bridge closed in May."},
                          {"id": 2, "text": "Because of that, traffic doubled on Route 9."}])
        self.assertEqual(len(planning.sentences(VI, "vi")), 2)
        self.assertEqual([s["text"] for s in planning.sentences(JA, "ja")], ["売上は20%増えた。", "しかし、利益は減少した。"])

    def test_protected_spans_do_not_split(self):
        text = "See https://example.com/a.b for details. Then run it."
        self.assertEqual(len(planning.sentences(text, "en")), 2)


class AnalysisTest(unittest.TestCase):
    FACTS = [{"id": "f1", "fact": "Traffic doubled on Route 9", "anchors": ["Route 9"]}]

    def errors(self, data, original=EN, code="en"):
        """Gate 1 errors for ``data``."""
        return planning.validate_analysis(data, original, code)[0]

    def test_valid_examples(self):
        self.assertEqual(self.errors({"facts": self.FACTS, "discourse": [{"from": 1, "to": 2, "type": "cause"}],
                                      "register": "neutral", "constraints": {"keep": ["Route 9"], "length_ratio": 0.8}}), [])
        vi = {"facts": [{"id": "f1", "fact": "Hòa nhạc dời sang thứ Bảy nếu mưa", "anchors": ["thứ Bảy"]}]}
        self.assertEqual(self.errors(vi, VI, "vi"), [])
        ja = {"facts": [{"id": "f1", "fact": "売上は20%増えた", "anchors": ["20%"]}],
              "discourse": [{"from": 1, "to": 2, "type": "contrast"}], "register": "formal"}
        self.assertEqual(self.errors(ja, JA, "ja"), [])

    def test_invented_anchor_and_limits(self):
        invented = [{"id": "f1", "fact": "Traffic tripled", "anchors": ["Route 66"]}]
        self.assertIn("anchor_not_in_original", types(self.errors({"facts": invented})))
        many = [{"id": f"f{i}", "fact": "x", "anchors": []} for i in range(13)]
        self.assertIn("too_many_facts", types(self.errors({"facts": many})))
        self.assertIn("fact_too_long", types(self.errors({"facts": [{"id": "f1", "fact": "x" * 121}]})))
        self.assertIn("invalid_facts", types(self.errors({"facts": []})))

    def test_unknown_sentence_ids_and_relations(self):
        bad = {"facts": self.FACTS, "discourse": [{"from": 1, "to": 3, "type": "cause"},
                                                  {"from": 2, "to": 2, "type": "because"},
                                                  {"from": "1", "to": 2, "type": "cause"}]}
        found = self.errors(bad)
        self.assertEqual([e for e in found if e["type"] == "unknown_sentence"],
                         [{"type": "unknown_sentence", "index": 1, "field": "to", "value": 3},
                          {"type": "unknown_sentence", "index": 3, "field": "from", "value": "1"}])
        self.assertEqual(sum(e["type"] == "invalid_discourse" for e in found), 2)  # bad type, from == to
        self.assertIn("invalid_discourse", types(self.errors({"facts": self.FACTS, "discourse": [{"from": 1}]})))

    def test_constraints_register_and_keys(self):
        self.assertIn("keep_not_in_original", types(self.errors({"facts": self.FACTS, "constraints": {"keep": ["Atlas"]}})))
        for ratio in (0, -1, 3.5, "0.7", True):
            with self.subTest(ratio=ratio):
                self.assertIn("invalid_constraints",
                              types(self.errors({"facts": self.FACTS, "constraints": {"length_ratio": ratio}})))
        self.assertIn("unknown_key", types(self.errors({"facts": self.FACTS, "constraints": {"tone": "x"}})))
        self.assertIn("invalid_register", types(self.errors({"facts": self.FACTS, "register": "grumpy"})))
        self.assertIn("unknown_key", types(self.errors({"facts": self.FACTS, "summary": "x"})))
        self.assertIn("invalid_artifact", types(self.errors([])))

    def test_fact_without_anchor_is_a_warning(self):
        errors, warnings = planning.validate_analysis({"facts": [{"id": "f1", "fact": "x"}]}, EN, "en")
        self.assertEqual(errors, [])
        self.assertEqual(types(warnings), {"fact_without_anchor"})


class PlanTest(unittest.TestCase):
    def errors(self, rows, original=EN, code="en", mode="standard", analysis=None, **extra):
        """Gate 2 errors for a plan made of ``rows``."""
        return planning.validate_plan(dict(extra, rows=rows), original, code, mode, analysis)[0]

    def test_valid_plans(self):
        self.assertEqual(self.errors([{"src": [1, 2], "ops": ["merge", "voice"], "target": 1}]), [])
        self.assertEqual(self.errors([{"src": [1], "ops": ["split", "lexical"], "target": 2},
                                      {"src": [2], "ops": ["keep"], "target": 1}], axis="Structure"), [])
        self.assertEqual(self.errors([{"src": [1], "ops": ["lexical"], "target": 1},
                                      {"src": [2], "ops": ["shorten"], "target": 0}], VI, "vi", "shorten"), [])
        self.assertEqual(self.errors([{"src": [2], "ops": ["reorder"], "target": 1},
                                      {"src": [1], "ops": ["lexical"], "target": 1}], JA, "ja"), [])

    def test_coverage(self):
        self.assertEqual(self.errors([{"src": [1], "ops": ["lexical"], "target": 1}]),
                         [{"type": "sentence_uncovered", "sentence": 2}])
        found = self.errors([{"src": [1], "ops": ["lexical"], "target": 1},
                             {"src": [1, 2], "ops": ["merge"], "target": 1}])
        self.assertEqual(found, [{"type": "sentence_covered_twice", "sentence": 1, "count": 2}])
        self.assertIn("unknown_sentence", types(self.errors([{"src": [1, 2, 3], "ops": ["merge"], "target": 1}])))

    def test_inconsistent_targets_and_ops(self):
        cases = {
            "inconsistent_target": [{"src": [1], "ops": ["split"], "target": 1},
                                    {"src": [2], "ops": ["lexical"], "target": 2}],
            "unknown_op": [{"src": [1], "ops": ["paraphrase"], "target": 1}, {"src": [2], "ops": ["keep"], "target": 1}],
        }
        for kind, rows in cases.items():
            with self.subTest(kind=kind):
                self.assertIn(kind, types(self.errors(rows)))
        rest = {"src": [2], "ops": ["keep"], "target": 1}
        for row in ({"src": [1], "ops": ["keep", "lexical"], "target": 1},
                    {"src": [1], "ops": ["split", "merge"], "target": 2}):
            self.assertIn("inconsistent_row", types(self.errors([row, rest])))
        self.assertIn("inconsistent_row", types(self.errors([{"src": [1, 2], "ops": ["lexical"], "target": 1}])))
        self.assertIn("inconsistent_target", types(self.errors([{"src": [1], "ops": ["shorten"], "target": 0}, rest])))
        self.assertIn("invalid_row", types(self.errors([{"src": [], "ops": ["keep"], "target": 1}, rest])))
        self.assertIn("invalid_artifact", types(self.errors([])))

    def test_length_goal(self):
        rows = [{"src": [1, 2], "ops": ["merge"], "target": 1}]
        self.assertIn("length_plan_mismatch", types(self.errors(rows, mode="shorten")))
        self.assertIn("length_plan_mismatch", types(self.errors(rows, mode="expand")))
        short = {"constraints": {"length_ratio": 0.7}}
        self.assertIn("length_plan_mismatch", types(self.errors(rows, analysis=short)))
        self.assertEqual(self.errors([{"src": [1, 2], "ops": ["merge", "shorten"], "target": 1}], analysis=short), [])
        self.assertIn("length_plan_mismatch", types(self.errors(
            [{"src": [1, 2], "ops": ["merge", "shorten", "expand"], "target": 1}], mode="shorten")))

    def test_light_mode_warns_on_structure(self):
        errors, warnings = planning.validate_plan({"rows": [{"src": [1, 2], "ops": ["merge"], "target": 1}]},
                                                  EN, "en", "light")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [{"type": "structural_op_in_light_mode", "row": 1, "ops": ["merge"]}])

    def test_mapping(self):
        plan = {"rows": [{"src": [1], "ops": ["split"], "target": 2}, {"src": [2], "ops": ["keep"], "target": 1}]}
        self.assertEqual(planning.mapping(plan), [{"src": [1], "target": 2, "ops": ["split"]},
                                                  {"src": [2], "target": 1, "ops": ["keep"]}])


class ReferenceExamplesTest(unittest.TestCase):
    """The JSON examples in analysis.md and plan.md stay valid JSON."""

    def test_json_blocks_parse(self):
        for name in ("analysis.md", "plan.md"):
            text = (REFERENCES / name).read_text(encoding="utf-8")
            blocks = re.findall(r"```json\n(.*?)```", text, re.DOTALL)
            self.assertGreaterEqual(len(blocks), 4, name)
            for block in blocks:
                json.loads(block)

    def test_listed_values_match_code(self):
        plan_doc = (REFERENCES / "plan.md").read_text(encoding="utf-8")
        for op in planning.OPS:
            self.assertIn(f"`{op}`", plan_doc)
        analysis_doc = (REFERENCES / "analysis.md").read_text(encoding="utf-8")
        for value in planning.DISCOURSE_TYPES + planning.REGISTERS:
            self.assertIn(f"`{value}`", analysis_doc)


class HarnessGatesTest(unittest.TestCase):
    """Gates 1–2 inside a session, and the analysis constraints at the text gate."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        """Write a JSON or text artifact into the session."""
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        (self.dir / name).write_text(text, encoding="utf-8")

    def test_plan_gate_and_state(self):
        harness.init(EN, self.dir, passes="plan,style")
        task = harness.next_task(self.dir)
        self.assertEqual(task["step"], "plan")
        self.assertEqual(len(task["sentences"]), 2)
        self.assertTrue(any(p.endswith("plan.md") for p in task["instructions"]))
        self.write("plan.json", {"rows": [{"src": [1], "ops": ["lexical"], "target": 1}]})
        result = harness.submit(self.dir)
        self.assertEqual(result["issues"], [{"type": "sentence_uncovered", "sentence": 2}])
        self.write("plan.json", {"rows": [{"src": [1, 2], "ops": ["merge"], "target": 1}]})
        self.assertTrue(harness.submit(self.dir)["ok"])
        self.assertNotIn("state", harness.next_task(self.dir))  # no analysis pass

    def test_constraints_flow_into_text_gate(self):
        harness.init(EN, self.dir, passes="analysis,style")
        self.write("analysis.json", {"facts": [{"id": "f1", "fact": "Traffic doubled on Route 9", "anchors": ["Route 9"]}],
                                     "constraints": {"keep": ["The bridge"], "length_ratio": 0.7}})
        self.assertTrue(harness.submit(self.dir)["ok"])
        task = harness.next_task(self.dir)
        self.assertIn("The bridge", task["constraints"]["protected"])
        self.assertEqual(task["constraints"]["length_ratio"], 0.7)
        self.write("p5-style.review.json", {"verdicts": [{"id": "f1", "verdict": "kept"}]})
        self.assertEqual(task["constraints"]["placeholders"], ["⟦P1⟧"])
        masked = (self.dir / "masked.txt").read_text(encoding="utf-8")
        self.assertTrue(masked.startswith("⟦P1⟧ closed in May."))
        self.write("p5-style.txt", "⟦P1⟧ shut in May, so Route 9 saw twice the traffic.")
        self.assertEqual(types(harness.submit(self.dir)["issues"]), {"length_target"})
        self.write("p5-style.txt", "A bridge shut in May. Route 9 traffic doubled.")
        self.assertTrue({"placeholder_missing", "protected_span_missing"} <= types(harness.submit(self.dir)["issues"]))
        self.write("p5-style.txt", "⟦P1⟧ shut in May; Route 9 traffic doubled.")
        result = harness.submit(self.dir)
        self.assertTrue(result["ok"], result["issues"])
        self.assertEqual((self.dir / "output.txt").read_text(encoding="utf-8"),
                         "The bridge shut in May; Route 9 traffic doubled.")


if __name__ == "__main__":
    unittest.main()
