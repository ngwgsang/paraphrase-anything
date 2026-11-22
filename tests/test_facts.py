"""Tests for the key-fact checklist (story 021): validation, verification, verdicts, CLI, docs."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import facts

PE = str(_path.SCRIPTS / "pe.py")
SKILL_DIR = Path(_path.SCRIPTS).parent

EN = "Acme funded the study. The team had 42 members in 2024."
EN_OK = "The 2024 study was paid for by Acme, and 42 people took part."
EN_BAD = "The 2024 study was paid for by Acme, and 41 people took part."
EN_FACTS = [
    {"id": "f1", "fact": "The team had 42 members in 2024", "anchors": ["42", "2024"]},
    {"id": "f2", "fact": "Acme funded the study", "anchors": ["Acme"]},
]

VI = "Vào năm 2023, công ty Hoàng Long đã đầu tư 50 tỷ đồng để mở rộng dây chuyền sản xuất."
VI_OK = "Công ty Hoàng Long rót 50 tỷ đồng trong năm 2023 nhằm nâng cấp dây chuyền sản xuất."
VI_BAD = "Công ty rót 60 tỷ đồng trong năm 2023 nhằm nâng cấp dây chuyền sản xuất."
VI_FACTS = [{"id": "f1", "fact": "Công ty đầu tư 50 tỷ đồng năm 2023", "anchors": ["50", "2023"]},
            {"id": "f2", "fact": "Công ty tên Hoàng Long", "anchors": ["Hoàng Long"]}]

JA = "同社は2024年に500人の新規採用を行い、海外事業の展開を加速させる計画である。"
JA_OK = "海外事業の拡大を速めるため、同社は2024年に500名を新たに採用する見通しだ。"
JA_BAD = "海外事業の拡大を速めるため、同社は2024年に300名を新たに採用する見通しだ。"
JA_FACTS = [{"id": "f1", "fact": "2024年に500人を採用する", "anchors": ["2024", "500"]}]


class ParseTest(unittest.TestCase):
    """Verify that malformed facts and verdicts are rejected."""

    def test_valid_facts_are_normalised(self):
        parsed = facts.parse_facts([{"id": "f1", "fact": " A fact ", "anchors": [" 42 "]}])
        self.assertEqual(parsed, [{"id": "f1", "fact": "A fact", "anchors": ["42"]}])

    def test_bad_shapes_raise(self):
        bad = [[], {}, ["x"], [{"fact": "no id"}], [{"id": "f1"}],
               [{"id": "f1", "fact": "x", "anchors": "42"}],
               [{"id": "f1", "fact": "x"}, {"id": "f1", "fact": "y"}]]
        for data in bad:
            with self.assertRaises(facts.FactsError, msg=str(data)):
                facts.parse_facts(data)

    def test_bad_verdicts_raise(self):
        for data in ({}, [{"verdict": "kept"}], [{"id": "f1", "verdict": "maybe"}],
                     [{"id": "f1", "verdict": "kept"}, {"id": "f1", "verdict": "lost"}]):
            with self.assertRaises(facts.FactsError, msg=str(data)):
                facts.parse_verdicts(data)


class ValidateTest(unittest.TestCase):
    """Verify validation against the original only (no rewrite)."""

    def test_valid_list_passes(self):
        report = facts.verify(EN, EN_FACTS)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["stage"], "validate")
        self.assertNotIn("kept", report)

    def test_invented_anchor_is_an_error(self):
        report = facts.verify(EN, [{"id": "f1", "fact": "Budget was 9 million", "anchors": ["9"]}])
        self.assertEqual([e["type"] for e in report["errors"]], ["anchor_not_in_original"])

    def test_fact_too_long(self):
        long_fact = [{"id": "f1", "fact": "word " * 40, "anchors": ["42"]}]
        report = facts.verify(EN, long_fact)
        self.assertIn("fact_too_long", [e["type"] for e in report["errors"]])

    def test_too_many_facts(self):
        many = [{"id": f"f{i}", "fact": "x", "anchors": ["42"]} for i in range(13)]
        report = facts.verify(EN, many)
        self.assertIn("too_many_facts", [e["type"] for e in report["errors"]])
        self.assertTrue(facts.verify(EN, many, max_facts=20)["ok"])

    def test_fact_without_anchor_warns(self):
        report = facts.verify(EN, [{"id": "f1", "fact": "Acme funded it", "anchors": []}])
        self.assertTrue(report["ok"])
        self.assertEqual([w["type"] for w in report["warnings"]], ["fact_without_anchor"])


class VerifyTest(unittest.TestCase):
    """Verify anchors in a rewrite for en, vi and ja."""

    def check_lang(self, original, good, bad, fact_list, missing):
        ok = facts.verify(original, fact_list, good)
        self.assertTrue(ok["ok"], ok)
        self.assertEqual(ok["kept"], ok["total"])
        report = facts.verify(original, fact_list, bad)
        self.assertFalse(report["ok"])
        self.assertIn(missing, [e["anchor"] for e in report["errors"] if e["type"] == "anchor_missing"])

    def test_english(self):
        self.check_lang(EN, EN_OK, EN_BAD, EN_FACTS, "42")

    def test_vietnamese(self):
        self.check_lang(VI, VI_OK, VI_BAD, VI_FACTS, "50")

    def test_japanese(self):
        self.check_lang(JA, JA_OK, JA_BAD, JA_FACTS, "500")

    def test_numbers_compare_by_value(self):
        original = "The fee was 1,000 dollars."
        fact_list = [{"id": "f1", "fact": "Fee is 1000", "anchors": ["1,000"]}]
        self.assertTrue(facts.verify(original, fact_list, "It cost 1000 dollars.", lang_code="en")["ok"])

    def test_names_match_as_whole_words(self):
        fact_list = [{"id": "f1", "fact": "Acme funded it", "anchors": ["Acme"]}]
        self.assertFalse(facts.verify(EN, fact_list, "Acmeville funded it.")["ok"])
        self.assertTrue(facts.verify(EN, fact_list, "ACME funded it.")["ok"])

    def test_missing_verdicts_warns(self):
        report = facts.verify(EN, EN_FACTS, EN_OK)
        self.assertEqual([w["type"] for w in report["warnings"]], ["no_verdicts"])


class VerdictTest(unittest.TestCase):
    """Verify enforcement of per-fact verdicts."""

    def verdicts(self, *pairs):
        """Build parsed verdicts from (id, verdict) pairs."""
        return facts.parse_verdicts([{"id": i, "verdict": v, "note": "n"} for i, v in pairs])

    def test_all_kept_passes(self):
        report = facts.verify(EN, EN_FACTS, EN_OK, self.verdicts(("f1", "kept"), ("f2", "kept")))
        self.assertTrue(report["ok"], report)

    def test_changed_and_lost_fail(self):
        report = facts.verify(EN, EN_FACTS, EN_OK, self.verdicts(("f1", "changed"), ("f2", "lost")))
        self.assertEqual(sorted(e["type"] for e in report["errors"]), ["fact_changed", "fact_lost"])
        self.assertEqual(report["kept"], 0)

    def test_missing_and_unknown_ids(self):
        report = facts.verify(EN, EN_FACTS, EN_OK, self.verdicts(("f1", "kept"), ("zz", "kept")))
        self.assertEqual(sorted(e["type"] for e in report["errors"]),
                         ["verdict_missing", "verdict_unknown_id"])


class FactsCliTest(unittest.TestCase):
    """Verify the pe facts command, flags and exit codes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        """Write JSON data to a temp file and return its path."""
        path = self.dir / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def run_pe(self, *args):
        """Run pe and return (exit code, parsed stdout, stderr)."""
        proc = subprocess.run([sys.executable, PE, *args], capture_output=True, text=True,
                              encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else {}, proc.stderr

    def test_validate_then_verify(self):
        path = self.write("facts.json", EN_FACTS)
        code, out, _ = self.run_pe("facts", "--original-text", EN, "--facts", path)
        self.assertEqual((code, out["stage"]), (0, "validate"))
        code, out, _ = self.run_pe("facts", "--original-text", EN, "--rewritten-text", EN_BAD,
                                   "--facts", path)
        self.assertEqual((code, out["ok"]), (1, False))

    def test_verdicts_flag(self):
        path = self.write("facts.json", EN_FACTS)
        verdicts = self.write("verdicts.json", [{"id": "f1", "verdict": "kept"},
                                                {"id": "f2", "verdict": "kept"}])
        code, out, _ = self.run_pe("facts", "--original-text", EN, "--rewritten-text", EN_OK,
                                   "--facts", path, "--verdicts", verdicts)
        self.assertEqual((code, out["ok"], out["kept"]), (0, True, 2))

    def test_verdicts_without_rewrite_is_usage_error(self):
        path = self.write("facts.json", EN_FACTS)
        verdicts = self.write("verdicts.json", [{"id": "f1", "verdict": "kept"}])
        code, _, err = self.run_pe("facts", "--original-text", EN, "--facts", path,
                                   "--verdicts", verdicts)
        self.assertNotEqual(code, 0)
        self.assertIn("--verdicts needs a rewrite", err)

    def test_malformed_facts_exit_2(self):
        path = self.write("facts.json", [{"id": "f1"}])
        code, out, _ = self.run_pe("facts", "--original-text", EN, "--facts", path)
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])

    def test_missing_facts_file_exit_2(self):
        code, out, _ = self.run_pe("facts", "--original-text", EN, "--facts",
                                   str(self.dir / "nope.json"))
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])

    def test_max_facts_flag(self):
        many = [{"id": f"f{i}", "fact": "x", "anchors": ["42"]} for i in range(3)]
        path = self.write("facts.json", many)
        code, out, _ = self.run_pe("facts", "--original-text", EN, "--facts", path, "--max-facts", "2")
        self.assertEqual(code, 1)
        self.assertEqual(out["errors"][0]["type"], "too_many_facts")


class FactsDocsTest(unittest.TestCase):
    """Verify the skill documents the key-fact step."""

    def test_skill_and_reference_describe_the_step(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        doc = (SKILL_DIR / "references" / "facts.md").read_text(encoding="utf-8")
        self.assertIn("references/facts.md", skill)
        self.assertIn("Extract key facts", skill)
        for phrase in ("120 characters", "anchors", "verdicts.json", "Independent pass"):
            self.assertIn(phrase, doc)
        response = (SKILL_DIR / "references" / "response.md").read_text(encoding="utf-8")
        self.assertIn("Key facts: N/N kept", response)


if __name__ == "__main__":
    unittest.main()
