"""Tests for agent-judged bidirectional entailment at the last text gate (story 025)."""

import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from _nli import judge_all
from paraphrase_everything import entailment, harness

CASES = {
    "en": {"original": "The team wrote the report in March. Sales rose by 5%.",
           "rewrite": "In March, the team produced the report. Sales went up by 5%.",
           "weaker": "In March, the team may have produced the report. Sales went up by 5%."},
    "vi": {"original": "Nhóm đã viết báo cáo vào tháng 3. Doanh thu tăng 5%.",
           "rewrite": "Vào tháng 3, nhóm đã hoàn thành báo cáo. Doanh thu đi lên 5%.",
           "weaker": "Vào tháng 3, nhóm có thể đã hoàn thành báo cáo. Doanh thu đi lên 5%."},
    "ja": {"original": "チームは3月に報告書を書いた。売上は5%増えた。",
           "rewrite": "チームは3月に報告書を作成した。売上は5%伸びた。",
           "weaker": "チームは3月に報告書を作成したかもしれない。売上は5%伸びた。"},
}
PLAN = {"rows": [{"src": [1], "ops": ["reorder", "lexical"], "target": 1},
                 {"src": [2], "ops": ["lexical"], "target": 1}]}
SWAPPED = {"rows": [{"src": [2], "ops": ["reorder", "lexical"], "target": 1},
                    {"src": [1], "ops": ["lexical"], "target": 1}]}


def types(issues):
    """The set of issue types."""
    return {i["type"] for i in issues}


def verdicts(found, **override):
    """An all-``entail`` verdict file for ``found`` pairs; ``override`` maps pair id to fields."""
    return {"pairs": [dict({"pair": p["pair"], "forward": "entail", "backward": "entail",
                            "evidence": {"src": p["original"], "rew": p["rewritten"]}, "reason": ""},
                           **override.get(p["pair"], {})) for p in found]}


class EntailmentGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "s"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        """Write a JSON or text file into the session."""
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        (self.dir / name).write_text(text, encoding="utf-8")

    def start(self, original, plan=PLAN, **kwargs):
        """Init a plan + style session and pass gate 2."""
        harness.init(original, self.dir, passes="plan,style", **kwargs)
        self.write("plan.json", plan)
        result = harness.submit(self.dir)
        self.assertTrue(result["ok"], result["issues"])

    def rewrite(self, text):
        """Write the style artifact and return the pairs to judge."""
        self.write("p5-style.txt", text)
        return harness.entailment_pairs(self.dir)["pairs"]

    def judge(self, found, **override):
        """Write verdicts and submit; return the issues."""
        self.write("p5-style.nli.json", verdicts(found, **override))
        return harness.submit(self.dir)["issues"]

    def test_plan_pairs_every_language(self):
        for code, case in CASES.items():
            with self.subTest(code=code):
                self.dir = Path(self.tmp.name) / code
                self.start(case["original"], lang_code=code)
                task = harness.next_task(self.dir)
                self.assertEqual(task["entailment"]["basis"], "plan")
                self.assertTrue(task["entailment"]["file"].endswith("p5-style.nli.json"))
                self.assertIn("entailment.md", [Path(p).name for p in task["instructions"]])
                found = self.rewrite(case["rewrite"])
                self.assertEqual([(p["pair"], p["src"]) for p in found], [("r1", [1]), ("r2", [2])])
                self.assertEqual(self.judge(found), [])
                report = harness.write_report(self.dir)
                self.assertEqual(report["entailment"],
                                 {"basis": "plan", "pairs": 2, "judge": "self", "judge_verified": False})

    def test_non_entail_verdict_fails_every_language(self):
        for code, case in CASES.items():
            with self.subTest(code=code):
                self.dir = Path(self.tmp.name) / code
                self.start(case["original"], lang_code=code)
                found = self.rewrite(case["weaker"])
                issues = self.judge(found, r1={"backward": "neutral", "reason": "adds doubt"})
                failed = [i for i in issues if i["type"] == "entailment_failed"]
                self.assertEqual([(i["pair"], i["direction"], i["verdict"]) for i in failed],
                                 [("r1", "backward", "neutral")])
                self.assertEqual(harness.next_task(self.dir)["issues"], issues)

    def test_contradict_always_fails(self):
        self.start(CASES["en"]["original"])
        found = self.rewrite(CASES["en"]["rewrite"])
        issues = self.judge(found, r2={"forward": "contradict", "backward": "contradict", "reason": "x"})
        self.assertEqual([i["direction"] for i in issues], ["forward", "backward"])

    def test_reordered_rows_pair_by_plan(self):
        self.start(CASES["en"]["original"], plan=SWAPPED)
        found = self.rewrite("Sales went up by 5%. In March, the team produced the report.")
        self.assertEqual([(p["pair"], p["src"], p["rewritten"]) for p in found],
                         [("r1", [2], "Sales went up by 5%."),
                          ("r2", [1], "In March, the team produced the report.")])

    def test_missing_file_and_missing_pairs(self):
        self.start(CASES["en"]["original"])
        found = self.rewrite(CASES["en"]["rewrite"])
        issues = harness.submit(self.dir)["issues"]
        self.assertEqual(issues, [{"type": "nli_file_missing", "file": "p5-style.nli.json", "pairs": ["r1", "r2"]}])
        data = verdicts(found)
        data["pairs"] = data["pairs"][:1] + [data["pairs"][0], {"pair": "r9"}]
        data["pairs"][0] = dict(data["pairs"][0], backward=None)
        self.write("p5-style.nli.json", data)
        issues = harness.submit(self.dir)["issues"]
        self.assertEqual([(i["type"], i["pair"]) for i in issues],
                         [("nli_duplicate_pair", "r1"), ("nli_unknown_pair", "r9"),
                          ("nli_missing_verdict", "r1"), ("nli_missing", "r2")])

    def test_invented_evidence_fails(self):
        self.start(CASES["vi"]["original"], lang_code="vi")
        found = self.rewrite(CASES["vi"]["rewrite"])
        issues = self.judge(found, r1={"evidence": {"src": "tháng 3", "rew": "tháng ba"}},
                            r2={"evidence": {"src": "  Doanh   thu ", "rew": ""}})
        self.assertEqual([(i["pair"], i["side"]) for i in issues], [("r1", "rew"), ("r2", "rew")])

    def test_invalid_file_and_judge(self):
        self.start(CASES["en"]["original"])
        found = self.rewrite(CASES["en"]["rewrite"])
        self.write("p5-style.nli.json", "{oops")
        self.assertEqual(types(harness.submit(self.dir)["issues"]), {"invalid_nli"})
        data = dict(verdicts(found), judge="me")
        self.write("p5-style.nli.json", data)
        self.assertEqual(types(harness.submit(self.dir)["issues"]), {"invalid_nli"})

    def test_independent_judge_is_reported_unverified(self):
        self.start(CASES["ja"]["original"], lang_code="ja")
        self.rewrite(CASES["ja"]["rewrite"])
        judge_all(self.dir, judge="independent")
        self.assertTrue(harness.submit(self.dir)["ok"])
        self.assertEqual(harness.write_report(self.dir)["entailment"]["judge"], "independent")
        self.assertFalse(harness.write_report(self.dir)["entailment"]["judge_verified"])

    def test_identical_pairs_are_skipped(self):
        self.start(CASES["en"]["original"], plan={"rows": [{"src": [1], "ops": ["lexical"], "target": 1},
                                                           {"src": [2], "ops": ["keep"], "target": 1}]})
        found = self.rewrite("In March, the team produced the report. Sales rose by 5%.")
        self.assertEqual([p["pair"] for p in found], ["r1"])

    def test_pairs_command_errors(self):
        self.start(CASES["en"]["original"])
        with self.assertRaises(harness.HarnessError):
            harness.entailment_pairs(self.dir)  # no rewrite yet
        harness.init(CASES["en"]["original"], Path(self.tmp.name) / "a", passes="analysis,style")
        with self.assertRaises(harness.HarnessError):
            harness.entailment_pairs(Path(self.tmp.name) / "a")  # not at the last pass

    def test_rewind_removes_verdicts(self):
        self.start(CASES["en"]["original"])
        self.rewrite(CASES["en"]["rewrite"])
        judge_all(self.dir)
        harness.rewind(self.dir, "style")
        self.assertFalse((self.dir / "p5-style.nli.json").exists())


class AlignerFallbackTest(unittest.TestCase):
    """Without pass 2 the pairs come from the deterministic aligner."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_aligner_pairs_every_language(self):
        for code, case in CASES.items():
            with self.subTest(code=code):
                session = self.dir / code
                harness.init(case["original"], session, passes="style", lang_code=code)
                self.assertEqual(harness.next_task(session)["entailment"]["basis"], "aligner")
                (session / "p5-style.txt").write_text(case["rewrite"], encoding="utf-8")
                found = judge_all(session)
                self.assertEqual([(p["pair"], p["src"]) for p in found], [("a1", [1]), ("a2", [2])])
                result = harness.submit(session)
                self.assertTrue(result["ok"], result["issues"])

    def test_aligner_groups_a_merge(self):
        found, basis = entailment.pairs("The team met on Monday. It approved the budget.",
                                        "On Monday the team met and approved the budget.", "en")
        self.assertEqual((basis, [p["src"] for p in found]), ("aligner", [[1, 2]]))


class WarningConflictTest(unittest.TestCase):
    """A ``pe check`` negation or hedge warning on a pair judged ``entail`` needs a reason."""

    SAMPLES = {
        "en": ("It is not uncommon for builds to fail.", "Builds commonly fail."),
        "vi": ("Kết quả này không phải là không đáng tin.", "Kết quả này khá đáng tin."),
        "ja": ("このテストは失敗しないわけではない。", "このテストは時々失敗する。"),
    }

    def test_flagged_pair_needs_a_reason(self):
        for code, (original, rewrite) in self.SAMPLES.items():
            with self.subTest(code=code):
                with tempfile.TemporaryDirectory() as tmp:
                    session = Path(tmp)
                    harness.init(original, session, passes="style", lang_code=code)
                    (session / "p5-style.txt").write_text(rewrite, encoding="utf-8")
                    found = harness.entailment_pairs(session)["pairs"]
                    self.assertEqual(found[0]["flags"], ["negation_mismatch"])
                    (session / "p5-style.review.json").write_text(
                        json.dumps({"accept": [{"id": "w1", "reason": "double negative made positive"}]}),
                        encoding="utf-8")
                    nli = session / "p5-style.nli.json"
                    nli.write_text(json.dumps(verdicts(found), ensure_ascii=False), encoding="utf-8")
                    issues = harness.submit(session)["issues"]
                    self.assertEqual([(i["type"], i["warnings"]) for i in issues],
                                     [("nli_reason_required", ["negation_mismatch"])])
                    data = verdicts(found, a1={"reason": "the double negative means it does happen"})
                    nli.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    self.assertTrue(harness.submit(session)["ok"])


class ShortenAsymmetryTest(unittest.TestCase):
    """Shortening may lose planned content (backward ``neutral``) but never add (forward)."""

    ORIGINAL = "Revenue rose 12% this year, mostly thanks to strong sales abroad. Costs stayed flat."
    SHORT = "Revenue rose 12% this year. Costs stayed flat."
    PLAN = {"rows": [{"src": [1], "ops": ["shorten"], "target": 1},
                     {"src": [2], "ops": ["lexical"], "target": 1}]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, plan):
        """A shorten-mode session at the style pass with the short rewrite written."""
        harness.init(self.ORIGINAL, self.dir, mode="shorten", passes="plan,style" if plan else "style")
        if plan:
            (self.dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            self.assertTrue(harness.submit(self.dir)["ok"])
        (self.dir / "p5-style.txt").write_text(self.SHORT, encoding="utf-8")
        found = harness.entailment_pairs(self.dir)["pairs"]
        return [p for p in found if p["original"] != p["rewritten"]]

    def submit(self, found, **override):
        """Write verdicts and submit; return the issue tuples."""
        (self.dir / "p5-style.nli.json").write_text(json.dumps(verdicts(found, **override)), encoding="utf-8")
        return [(i["type"], i.get("pair"), i.get("direction")) for i in harness.submit(self.dir)["issues"]]

    def test_backward_neutral_allowed_on_shorten_rows_with_reason(self):
        found = self.session(self.PLAN)
        self.assertEqual([(p["pair"], p["may_drop"]) for p in found], [("r1", True)])
        self.assertEqual(self.submit(found, r1={"backward": "neutral"}),
                         [("entailment_failed", "r1", "backward")])  # no reason
        self.assertEqual(self.submit(found, r1={"forward": "neutral", "reason": "shortened"}),
                         [("entailment_failed", "r1", "forward")])
        self.assertEqual(self.submit(found, r1={"backward": "neutral", "reason": "drops the reason"}), [])

    def test_rows_without_shorten_op_stay_strict(self):
        plan = {"rows": [{"src": [1], "ops": ["lexical"], "target": 1},
                         {"src": [2], "ops": ["shorten"], "target": 1}]}
        found = self.session(plan)
        self.assertFalse(found[0]["may_drop"])
        self.assertEqual(self.submit(found, r1={"backward": "neutral", "reason": "drops the reason"}),
                         [("entailment_failed", "r1", "backward")])

    def test_aligner_fallback_uses_the_mode(self):
        found = self.session(None)
        self.assertTrue(all(p["may_drop"] for p in found))
        self.assertEqual(self.submit(found, a1={"backward": "neutral", "reason": "drops the reason"}), [])


if __name__ == "__main__":
    unittest.main()
