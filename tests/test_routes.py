"""Tests for the Files, Long, and Variants routes inside harness sessions (story 027)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from _nli import judge_all
from paraphrase_everything import harness, routes

PE = Path(_path.SCRIPTS) / "pe.py"

MARKDOWN = """---
title: Notes
---
# Release notes

The team shipped version 2 in March. It fixed 12 bugs.

```python
print("unchanged")
```

- Faster builds for every user.
"""
MD_REWRITE = "Release notes\n\nIn March the team shipped version 2. It fixed 12 bugs.\n\nEvery user gets faster builds."
SRT = {
    "vi": ("1\n00:00:01,000 --> 00:00:03,000\nXin chào các bạn.\n\n"
           "2\n00:00:03,500 --> 00:00:06,000\nHôm nay chúng ta học 3 bài.\n",
           "Chào mọi người.\n\nHôm nay ta sẽ học 3 bài."),
    "ja": ("1\n00:00:01,000 --> 00:00:03,000\nみなさん、こんにちは。\n\n"
           "2\n00:00:03,500 --> 00:00:06,000\n今日は3つの課を学びます。\n",
           "皆さん、こんにちは。\n\n本日は3つの課を学習します。"),
    "en": ("1\n00:00:01,000 --> 00:00:03,000\nHello, everyone.\n\n"
           "2\n00:00:03,500 --> 00:00:06,000\nToday we cover 3 lessons.\n",
           "Hi, everyone.\n\nToday we will go through 3 lessons."),
}
COLOURS = ("red", "blue", "green", "amber", "violet", "silver")


def long_text():
    """A text above the chunking threshold: 60 paragraphs of 6 numbered sentences."""
    paragraphs = []
    for p in range(60):
        sentences = [f"The {COLOURS[s]} group got build {p * 6 + s} from Acme after a long review."
                     for s in range(6)]
        paragraphs.append(" ".join(sentences))
    return "\n\n".join(paragraphs) + "\n"


def types(issues):
    """The set of issue types."""
    return {i["type"] for i in issues}


class FilesRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "s"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        """Write a file into the session."""
        (self.dir / name).write_text(text, encoding="utf-8")

    def test_markdown_is_rebuilt_around_the_rewritten_prose(self):
        state = harness.init(MARKDOWN, self.dir, passes="style", fmt="markdown")
        self.assertEqual((state["format"], state["segments"]), ("markdown", 3))
        original = (self.dir / "original.txt").read_text(encoding="utf-8")
        self.assertEqual(original, "Release notes\n\nThe team shipped version 2 in March. It fixed 12 bugs.\n\n"
                                   "Faster builds for every user.")
        task = harness.next_task(self.dir)
        self.assertEqual(task["constraints"]["segments"], 3)
        self.assertIn("routes.md", [Path(p).name for p in task["instructions"]])
        self.write("p5-style.txt", MD_REWRITE.replace("\n\nEvery", " Every"))
        judge_all(self.dir)
        issues = harness.submit(self.dir)["issues"]
        self.assertIn(("segment_count_changed", 3, 2),
                      [(i["type"], i.get("expected"), i.get("got")) for i in issues])
        self.write("p5-style.txt", MD_REWRITE)
        judge_all(self.dir)
        result = harness.submit(self.dir)
        self.assertTrue(result["ok"], result["issues"])
        rebuilt = (self.dir / "output.md").read_text(encoding="utf-8")
        self.assertIn("title: Notes", rebuilt)
        self.assertIn('print("unchanged")', rebuilt)
        self.assertIn("# Release notes", rebuilt)
        self.assertIn("In March the team shipped version 2. It fixed 12 bugs.", rebuilt)
        self.assertIn("- Every user gets faster builds.", rebuilt)
        report = harness.write_report(self.dir)
        self.assertTrue(report["output"].endswith("output.md"))
        self.assertEqual(harness.next_task(self.dir)["output"], report["output"])

    def test_subtitles_keep_cues_every_language(self):
        for code, (source, rewrite) in SRT.items():
            with self.subTest(code=code):
                session = Path(self.tmp.name) / code
                harness.init(source, session, passes="style", fmt="srt", lang_code=code, gates="")
                (session / "p5-style.txt").write_text(rewrite, encoding="utf-8")
                result = harness.submit(session)
                self.assertTrue(result["ok"], result["issues"])
                rebuilt = (session / "output.srt").read_text(encoding="utf-8")
                self.assertIn("00:00:03,500 --> 00:00:06,000", rebuilt)
                self.assertEqual(rebuilt.count("-->"), 2)
                self.assertIn(rewrite.split("\n\n")[1], rebuilt)

    def test_source_file_is_pinned(self):
        harness.init(MARKDOWN, self.dir, passes="style", fmt="markdown")
        self.write("source.md", MARKDOWN + "\nMore.\n")
        with self.assertRaises(harness.HarnessError):
            harness.next_task(self.dir)

    def test_file_without_prose_is_rejected(self):
        with self.assertRaises(harness.HarnessError):
            harness.init("```\ncode only\n```\n", self.dir, fmt="markdown")
        with self.assertRaises(harness.HarnessError):
            harness.init("text", self.dir, fmt="docx")


class LongRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "s"
        self.text = long_text()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, data):
        """Write JSON or text to ``path`` (relative to the session unless absolute)."""
        path = Path(path) if Path(path).is_absolute() else self.dir / path
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")

    def start(self):
        """A long analysis + plan + style session through gate 2."""
        state = harness.init(self.text, self.dir, passes="analysis,plan,style")
        self.assertTrue(state["long"])
        task = harness.next_task(self.dir)
        self.assertIn("Acme", [e["term"] for e in task["glossary_candidates"]])
        self.write("analysis.json", {"facts": [{"id": "f1", "fact": "Build 7 shipped", "anchors": ["build 7"]}],
                                     "glossary": [{"term": "Acme", "decision": "keep", "rendering": None}]})
        result = harness.submit(self.dir)
        self.assertTrue(result["ok"], result["issues"])
        task = harness.next_task(self.dir)
        self.assertGreater(len(task["chunks"]), 1)
        return task

    def plan(self, n):
        """A plan with one lexical row per sentence."""
        return {"rows": [{"src": [i], "ops": ["lexical"], "target": 1} for i in range(1, n + 1)]}

    def test_long_session_rewrites_chunk_by_chunk(self):
        task = self.start()
        n = sum(len(c["sentences"]) for c in task["chunks"])
        self.write("plan.json", self.plan(n))
        self.assertTrue(harness.submit(self.dir)["ok"])
        self.write("p5-style.review.json", {"verdicts": [{"id": "f1", "verdict": "kept"}]})
        chunks = len(task["chunks"])
        for k in range(chunks):
            task = harness.next_task(self.dir)
            self.assertEqual(task["chunk"], {"index": k + 1, "of": chunks})
            self.assertEqual(task["constraints"]["glossary"][0]["term"], "Acme")
            self.assertEqual({r["src"][0] for r in task["plan"]}, set(task_sentences(self, k)))
            if k:
                self.assertTrue(task["context"]["previous_rewritten"].startswith("The "))
            text = Path(task["inputs"]["previous"]).read_text(encoding="utf-8")
            self.write(task["output"], text.replace("after a long review", "following a long review"))
            if k == chunks - 1:
                self.assertIn("entailment", task)
                self.assertGreater(len(judge_all(self.dir)), 0)
            else:
                self.assertNotIn("entailment", task)
            result = harness.submit(self.dir)
            self.assertTrue(result["ok"], result["issues"])
        self.assertEqual(result["status"], "complete")
        report = harness.write_report(self.dir)
        self.assertEqual((report["long"], report["facts"]["total"], report["facts"]["kept"]), (True, 1, 1))
        self.assertEqual((self.dir / "output.txt").read_text(encoding="utf-8"),
                         self.text.replace("after a long review", "following a long review"))

    def test_glossary_term_lost_returns_a_fix_round_over_all_chunks(self):
        harness.init(self.text, self.dir, passes="style")
        chunks = len(harness.next_task(self.dir) and harness._chunks(self.dir, harness.load(self.dir))[0])
        for k in range(chunks):
            task = harness.next_task(self.dir)
            text = Path(task["inputs"]["previous"]).read_text(encoding="utf-8")
            if k == 1:
                text = text.replace("from Acme", "from the firm", 1)
            self.write(task["output"], text)
            if k == chunks - 1:
                judge_all(self.dir)
            result = harness.submit(self.dir)
        self.assertIn("term_lost", types(result["issues"]))
        task = harness.next_task(self.dir)
        self.assertTrue(task["chunk"]["fix"])
        self.assertEqual(len(task["chunk_files"]), chunks)
        second = Path(task["chunk_files"][1])
        self.write(second, second.read_text(encoding="utf-8").replace("from the firm", "from Acme"))
        result = harness.submit(self.dir)
        self.assertTrue(result["ok"], result["issues"])

    def test_plan_rows_must_stay_inside_chunks(self):
        task = self.start()
        first, second = task["chunks"][0]["sentences"], task["chunks"][1]["sentences"]
        plan = self.plan(sum(len(c["sentences"]) for c in task["chunks"]))
        rows = plan["rows"]
        a, b = first[-1] - 1, second[0] - 1
        rows[a:b + 1] = [{"src": [first[-1], second[0]], "ops": ["merge"], "target": 1}]
        self.write("plan.json", plan)
        self.assertIn("plan_crosses_chunk", types(harness.submit(self.dir)["issues"]))

    def test_rewind_removes_chunk_files(self):
        harness.init(self.text, self.dir, passes="style")
        task = harness.next_task(self.dir)
        self.write(task["output"], Path(task["inputs"]["previous"]).read_text(encoding="utf-8"))
        harness.submit(self.dir)
        harness.rewind(self.dir, "style")
        self.assertFalse((self.dir / "p5-style.chunks").exists())
        self.assertEqual(harness.next_task(self.dir)["chunk"]["index"], 1)


def task_sentences(test, k):
    """Sentence ids of chunk ``k`` (0-based) in the test's session."""
    of = harness._sentence_chunks(test.dir, harness.load(test.dir))
    return [i for i, c in of.items() if c == k]


class VariantsRouteTest(unittest.TestCase):
    CASES = {
        "en": ("The team wrote the report in March. Sales rose by 5%.",
               "In March, the team produced the report. Sales went up by 5%.",
               "The report was finished by the team in March, and sales climbed 5%."),
        "vi": ("Nhóm đã viết báo cáo vào tháng 3. Doanh thu tăng 5%.",
               "Vào tháng 3, nhóm đã hoàn thành báo cáo. Doanh thu đi lên 5%.",
               "Báo cáo được nhóm soạn xong trong tháng 3, còn doanh thu nhích thêm 5%."),
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def plans(self):
        """Two variant plans with distinct axes."""
        return {"variants": [
            {"axis": "vocabulary", "rows": [{"src": [1], "ops": ["reorder", "lexical"], "target": 1},
                                            {"src": [2], "ops": ["lexical"], "target": 1}]},
            {"axis": "structure", "rows": [{"src": [1, 2], "ops": ["merge", "voice"], "target": 1}]}]}

    def test_two_variants_with_pairwise_gate(self):
        for code, (original, v1, v2) in self.CASES.items():
            with self.subTest(code=code):
                session = Path(self.tmp.name) / code
                harness.init(original, session, passes="plan,style", variants=2, lang_code=code)
                task = harness.next_task(session)
                self.assertEqual(task["variants"], 2)
                self.assertIn("variants.md", [Path(p).name for p in task["instructions"]])
                (session / "plan.json").write_text(json.dumps(self.plans()), encoding="utf-8")
                self.assertTrue(harness.submit(session)["ok"])

                task = harness.next_task(session)
                self.assertEqual(task["variant"], {"id": "v1", "index": 1, "of": 2, "axis": "vocabulary"})
                self.assertTrue(task["output"].endswith("p5-style.v1.txt"))
                (session / "p5-style.v1.txt").write_text(v1, encoding="utf-8")
                self.assertEqual(judge_all(session)[0]["pair"], "r1")
                result = harness.submit(session)
                self.assertTrue(result["ok"], result["issues"])
                self.assertEqual(result["next_variant"], "v2")

                task = harness.next_task(session)
                self.assertEqual((task["variant"]["id"], len(task["plan"])), ("v2", 1))
                close = v1.replace(". ", ", and ", 1).replace(", and S", ", and s").replace(", and D", ", and d")
                (session / "p5-style.v2.txt").write_text(close, encoding="utf-8")  # one sentence, close to v1
                judge_all(session)
                result = harness.submit(session)
                self.assertTrue(result["ok"])  # its own gate passes...
                self.assertEqual(types(result["pairwise"]), {"variants_too_similar"})  # ...but not the pair
                self.assertEqual(result["status"], "in_progress")
                task = harness.next_task(session)
                self.assertEqual((task["variant"]["id"], types(task["issues"])), ("v2", {"variants_too_similar"}))

                (session / "p5-style.v2.txt").write_text(v2, encoding="utf-8")
                judge_all(session)
                result = harness.submit(session)
                self.assertTrue(result["ok"], result["issues"])
                self.assertEqual(result["status"], "complete")
                report = harness.write_report(session)
                self.assertEqual([(v["variant"], v["axis"]) for v in report["variants"]],
                                 [("v1", "vocabulary"), ("v2", "structure")])
                self.assertEqual((session / "output.v2.txt").read_text(encoding="utf-8"), v2)
                self.assertEqual([g["gate"] for g in report["gates_run"]], ["g2", "g5", "g5", "gv", "g5", "gv"])
                self.assertEqual(report["entailment"]["judge"], "self")
                self.assertEqual(len(harness.next_task(session)["outputs"]), 2)

    def test_variant_plan_validation(self):
        session = Path(self.tmp.name) / "p"
        harness.init(self.CASES["en"][0], session, passes="plan,style", variants=2)
        plans = self.plans()
        plans["variants"][1]["axis"] = "Vocabulary"
        plans["variants"][1]["rows"] = [{"src": [1], "ops": ["lexical"], "target": 1}]
        (session / "plan.json").write_text(json.dumps(plans), encoding="utf-8")
        found = {(i["type"], i.get("variant")) for i in harness.submit(session)["issues"]}
        self.assertIn(("variant_axis_duplicate", "v2"), found)
        self.assertIn(("sentence_uncovered", "v2"), found)
        (session / "plan.json").write_text(json.dumps({"variants": plans["variants"][:1]}), encoding="utf-8")
        self.assertIn("variant_count", types(harness.submit(session)["issues"]))

    def test_init_rejects_impossible_variants(self):
        root = Path(self.tmp.name)
        with self.assertRaises(harness.HarnessError):
            harness.init("One sentence.", root / "a", passes="style", variants=2)
        with self.assertRaises(harness.HarnessError):
            harness.init("One sentence.", root / "b", variants=routes.MAX_VARIANTS + 1)
        with self.assertRaises(harness.HarnessError):
            harness.init(long_text(), root / "c", variants=2)


class CliRouteTest(unittest.TestCase):
    def pe(self, *args):
        """Run ``pe`` in a new process; return (exit code, JSON output)."""
        proc = subprocess.run([sys.executable, str(PE), *args], capture_output=True, text=True,
                              encoding="utf-8", input="")
        return proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else proc.stderr

    def test_init_detects_the_file_format_and_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "notes.md"
            source.write_text(MARKDOWN, encoding="utf-8")
            code, out = self.pe("run", "init", str(source), "-o", str(Path(tmp) / "s"), "--preset", "fast")
            self.assertEqual((code, out["format"]), (0, "markdown"))
            code, out = self.pe("run", "init", str(source), "-o", str(Path(tmp) / "v"), "--variants", "3",
                                "--passes", "plan,style")
            self.assertEqual((code, out["variants"]), (0, ["v1", "v2", "v3"]))
            self.assertEqual(self.pe("run", "next", str(Path(tmp) / "v"), "--variants", "2")[0], 2)


if __name__ == "__main__":
    unittest.main()
