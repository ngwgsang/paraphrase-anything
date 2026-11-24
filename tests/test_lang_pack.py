"""Tests for the language-pack contract: schema, fixtures, tiers, scaffold (story 012 phase 2)."""

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import check, lang, metrics
from paraphrase_everything.lang import pack

PE = Path(_path.SCRIPTS) / "pe.py"


def raw(code):
    """The raw JSON of an installed pack, without defaults merged."""
    return json.loads((lang.LANG_DIR / f"{code}.json").read_text(encoding="utf-8"))


class InstalledPacksTest(unittest.TestCase):
    """Every installed pack must satisfy the contract; this is what registers a language."""

    def test_schema(self):
        for code in lang.available():
            self.assertEqual(pack.validate(raw(code), code), [], code)

    def test_fixtures(self):
        for code in lang.available():
            self.assertEqual(pack.run_fixtures(code), [], code)

    def test_every_pack_is_at_least_tier_1(self):
        for row in pack.coverage_table():
            self.assertGreaterEqual(row["tier"], 1, row)

    def test_tier_2_needs_eval_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = pack.coverage("en", evals_dir=tmp)
        self.assertEqual(row["tier"], 1)
        self.assertEqual(row["eval_cases"], 0)
        self.assertIsNone(pack.coverage("en", evals_dir=Path(tmp) / "missing")["eval_cases"])
        self.assertEqual(pack.coverage("en")["tier"], 2)

    def test_no_language_codes_in_core_code(self):
        """A language is added by data alone, so no core module may name one."""
        codes = set(lang.available())
        for py in (Path(_path.SCRIPTS) / "paraphrase_everything").rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(names & codes, f"{py.name} names {names & codes}")


class ChineseProofTest(unittest.TestCase):
    """zh was added at tier 1 with data and a language note only."""

    def test_detect_and_tier(self):
        self.assertEqual(lang.detect("研究人员在2024年发表了这项成果。"), "zh")
        self.assertEqual(pack.coverage("zh")["tier"], 1)

    def test_check_uses_zh_markers(self):
        report = check.check("他今天不来，可能明天来。", "他今天来，明天来。")
        self.assertEqual(report["lang"], "zh")
        self.assertEqual({w["type"] for w in report["warnings"]}, {"negation_mismatch", "hedge_mismatch"})
        self.assertIn("proper_noun", report["unsupported"])

    def test_check_counts_numbers(self):
        report = check.check("公司有300名员工。", "公司有约350名员工。", lang_code="zh")
        self.assertEqual({e["type"] for e in report["errors"]}, {"number_missing", "number_extra"})

    def test_metrics_count_characters(self):
        result = metrics.compare("会议推迟了。", "会议延期了。", lang_code="zh")
        self.assertEqual(result["length_unit"], "char")
        self.assertEqual(result["length"], {"original": 5, "rewritten": 5})


class ValidateTest(unittest.TestCase):
    """The schema check reports each kind of problem."""

    def setUp(self):
        self.good = raw("zh")

    def problems(self, **changes):
        """Validate a copy of the zh pack with ``changes`` applied (None deletes a key)."""
        data = dict(self.good)
        for key, value in changes.items():
            if value is None:
                data.pop(key)
            else:
                data[key] = value
        return pack.validate(data, "zh")

    def test_good_pack(self):
        self.assertEqual(self.problems(), [])

    def test_missing_and_unknown_keys(self):
        self.assertIn("missing key: negation_markers", self.problems(negation_markers=None))
        self.assertIn("unknown key: colour", self.problems(colour="red"))

    def test_types_and_values(self):
        self.assertIn("length_unit: must be one of word, char", self.problems(length_unit="syllable"))
        self.assertIn("hedge_markers: must be a list of non-empty strings", self.problems(hedge_markers=[""]))
        self.assertIn("code: must be 'zh' (the file name)", self.problems(code="cn"))
        self.assertIn("sentence_terminators: must not be empty", self.problems(sentence_terminators=[]))
        self.assertIn("decimal_separator and thousands_separator must differ",
                      self.problems(thousands_separator="."))

    def test_detect_block(self):
        self.assertTrue(any("invalid regex" in p for p in self.problems(detect={"script": "["})))
        self.assertIn("detect: unknown key weight", self.problems(detect={"weight": 1}))
        self.assertIn("detect.priority: wrong type", self.problems(detect={"priority": True}))

    def test_fixture_shape(self):
        self.assertIn("fixtures: unknown key samples", self.problems(fixtures={"samples": []}))
        self.assertTrue(any("fixtures.sentences" in p
                            for p in self.problems(fixtures={"sentences": [{"text": "x"}]})))


class RunFixturesTest(unittest.TestCase):
    """Fixtures catch packs whose data does not do what its samples claim."""

    def test_failures_are_reported(self):
        data = raw("zh")
        data["fixtures"] = {"detect": ["The weather is nice."],
                            "sentences": [{"text": "会议推迟了。我们明天再谈。", "count": 1}],
                            "negation": ["今天天气很好。"], "hedge": []}
        failures = pack.run_fixtures("zh", data)
        self.assertTrue(any(f.startswith("detect:") for f in failures))
        self.assertTrue(any(f.startswith("sentences:") for f in failures))
        self.assertTrue(any(f.startswith("negation:") for f in failures))
        self.assertIn("fixtures.hedge: add a sample for the hedge markers", failures)

    def test_empty_fixtures_are_not_enough(self):
        failures = pack.run_fixtures("zh", dict(raw("zh"), fixtures={}))
        self.assertIn("fixtures.detect: add at least one sample text", failures)
        self.assertIn("fixtures.sentences: add at least one {text, count} case", failures)


class ScaffoldTest(unittest.TestCase):
    """``pe lang new`` writes a pack that validates but still needs fixtures."""

    def test_scaffold_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path, note_path = map(Path, pack.scaffold("ko", "한국어", skill_dir=tmp))
            data = json.loads(data_path.read_text(encoding="utf-8"))
            note = note_path.read_text(encoding="utf-8")
            with self.assertRaises(FileExistsError):
                pack.scaffold("ko", "한국어", skill_dir=tmp)
        self.assertEqual(data_path.name, "ko.json")
        self.assertEqual(pack.validate(data, "ko"), [])
        self.assertTrue(pack.run_fixtures("ko", data))
        self.assertIn("**Table headers:**", note)
        self.assertIn("# 한국어 notes", note)

    def test_char_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(pack.scaffold("th", "Thai", skill_dir=tmp, length_unit="char")[0])
            data = json.loads(data_path.read_text(encoding="utf-8"))
        self.assertEqual((data["length_unit"], data["match"], data["has_case"]), ("char", "substring", False))

    def test_invalid_code(self):
        for code in ("KO", "korean", "default", "k"):
            with self.assertRaises(ValueError):
                pack.scaffold(code, "x", skill_dir="unused")

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, str(PE), "lang", "new", "pt-br", "--name", "Português", "--skill-dir", tmp]
            first = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            second = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(len(result["created"]), 2)
        self.assertTrue(result["next"])
        self.assertEqual(second.returncode, 2)
        self.assertIn("already exists", json.loads(second.stdout)["error"])


class LangsCliTest(unittest.TestCase):
    """``pe langs`` reports the coverage table."""

    def test_langs(self):
        proc = subprocess.run([sys.executable, str(PE), "langs"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        rows = {row["code"]: row for row in json.loads(proc.stdout)["langs"]}
        self.assertEqual(rows["zh"]["tier"], 1)
        self.assertEqual(rows["ja"]["checks"]["proper_noun"], False)
        self.assertEqual(rows["en"]["problems"], [])


if __name__ == "__main__":
    unittest.main()
