"""Tests for the readability and repetition lint (story 005)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import lang, lint

PE = Path(__file__).resolve().parent.parent / "skills" / "paraphrase-anything" / "scripts" / "pe.py"


def rules_of(report):
    """``(rule, text)`` of every finding, in order."""
    return [(f["rule"], f["text"]) for f in report["findings"]]


class FindingShapeTest(unittest.TestCase):
    """Every finding carries a rule id, span offsets into the rewrite, and a hint."""

    def test_fields_and_offsets(self):
        text = "However, it failed. However, it worked — and then — it stopped. It is worth noting that it ran."
        report = lint.lint(text, lang_code="en")
        self.assertTrue(report["ok"])
        self.assertTrue(report["findings"])
        for n, f in enumerate(report["findings"], 1):
            self.assertEqual(f["id"], f"l{n}")
            self.assertIn(f["severity"], lint.SEVERITIES)
            self.assertEqual(text[f["start"]:f["end"]], f["text"])
            self.assertTrue(f["hint"])

    def test_counts_by_severity(self):
        report = lint.lint("However, a. However, b.", lang_code="en")
        self.assertEqual(report["counts"], {"warn": 1, "info": 0})


class PhraseRulesTest(unittest.TestCase):
    """Clichés and connectors come from the language data."""

    def test_cliche_en(self):
        report = lint.lint("We delve into the data.", lang_code="en")
        self.assertIn(("cliche", "delve into"), rules_of(report))

    def test_cliche_kept_from_the_original_is_not_flagged(self):
        original = "It is worth noting that sales rose."
        report = lint.lint("It is worth noting that sales went up.", original, lang_code="en")
        self.assertNotIn("cliche", [f["rule"] for f in report["findings"]])

    def test_connector_repeat_vi(self):
        report = lint.lint("Tuy nhiên, dự án chậm. Tuy nhiên, đội vẫn xong.", lang_code="vi")
        self.assertEqual(rules_of(report), [("connector_repeat", "Tuy nhiên")])

    def test_connector_repeat_ja(self):
        report = lint.lint("しかし、計画は失敗した。しかし、再挑戦した。", lang_code="ja")
        self.assertEqual(rules_of(report), [("connector_repeat", "しかし、")])

    def test_repeat_outside_the_window_is_fine(self):
        text = "However, a. B came late in the day. C came. However, d."
        self.assertEqual(lint.lint(text, lang_code="en")["findings"], [])

    def test_connector_matching_is_word_bounded_en(self):
        self.assertEqual(lint.lint("Thusly it went. Thusly again.", lang_code="en")["findings"], [])

    def test_connector_added_needs_the_original(self):
        report = lint.lint("Moreover, costs fell.", lang_code="en")
        self.assertEqual(report["skipped"], [{"rule": "connector_added", "why": "needs the original (--original)"}])

    def test_connector_added_counts_against_the_original(self):
        original = "Costs fell. However, prices rose."
        report = lint.lint("However, costs fell. However, prices rose.", original, lang_code="en")
        added = [f for f in report["findings"] if f["rule"] == "connector_added"]
        self.assertEqual([(f["start"], f["original_count"]) for f in added], [(21, 1)])

    def test_connector_added_vi(self):
        report = lint.lint("Ngoài ra, giá tăng.", "Giá tăng.", lang_code="vi")
        self.assertIn(("connector_added", "Ngoài ra"), rules_of(report))

    def test_language_without_phrases_is_skipped(self):
        report = lint.lint("Hola. Hola.", lang_code="xx")
        self.assertIn("cliche", [s["rule"] for s in report["skipped"]])


class ShapeRulesTest(unittest.TestCase):
    """Dash density and sentence-length uniformity."""

    def test_dash_density(self):
        report = lint.lint("It rose — fast — and fell — slowly.", lang_code="en")
        self.assertEqual([f["rule"] for f in report["findings"]], ["dash_density"] * 3)

    def test_few_dashes_are_fine(self):
        text = "It rose — fast. Then it fell. Prices held. Buyers waited."
        self.assertEqual(lint.lint(text, lang_code="en")["findings"], [])

    def test_dashes_inside_code_are_ignored(self):
        text = "Run `a — b — c` once."
        self.assertEqual(lint.lint(text, lang_code="en")["findings"], [])

    def test_uniform_sentence_lengths(self):
        text = "The cat sat down. The dog ran off. The bird flew up. The fish swam on."
        report = lint.lint(text, lang_code="en")
        [finding] = report["findings"]
        self.assertEqual((finding["rule"], finding["start"], finding["end"]), ("sentence_length_uniform", 0, len(text)))
        self.assertEqual(finding["lengths"], [4, 4, 4, 4])

    def test_varied_sentence_lengths_are_fine(self):
        text = "It sat. The dog ran off across the wide field at dawn. Birds flew. Then the fish swam on."
        self.assertEqual(lint.lint(text, lang_code="en")["findings"], [])

    def test_uniform_ja_counts_characters(self):
        text = "猫が座った。犬が走った。鳥が飛んだ。魚が泳いだ。"
        self.assertEqual([f["rule"] for f in lint.lint(text, lang_code="ja")["findings"]], ["sentence_length_uniform"])


class RuleFilesTest(unittest.TestCase):
    """Rules are data: defaults in lint.json, extra files add, override, or disable by id."""

    def write_rules(self, tmp, name, rules):
        """Write a rule file into ``tmp``."""
        Path(tmp, name).write_text(json.dumps({"rules": rules}), encoding="utf-8")

    def test_defaults_come_from_the_data_file(self):
        ids = [r["id"] for r in lint.load_rules()]
        data = json.loads(lint.RULES_FILE.read_text(encoding="utf-8"))
        self.assertEqual(ids, [r["id"] for r in data["rules"]])

    def test_extra_rules_add_override_and_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_rules(tmp, "a.json", [
                {"id": "house", "kind": "phrases", "severity": "info", "phrases": {"en": ["utilize"]}, "hint": "Say use."},
                {"id": "connector_repeat", "kind": "repeat", "source": "connectors", "severity": "info", "window": 10},
                {"id": "dash_density", "enabled": False},
            ])
            rules = lint.load_rules(tmp)
        ids = [r["id"] for r in rules]
        self.assertIn("house", ids)
        self.assertNotIn("dash_density", ids)
        report = lint.lint("However, we utilize it. A. B. However — x — y — z.", lang_code="en", rules=rules)
        found = {(f["rule"], f["severity"]) for f in report["findings"]}
        self.assertIn(("house", "info"), found)
        self.assertIn(("connector_repeat", "info"), found)
        self.assertNotIn("dash_density", {f["rule"] for f in report["findings"]})

    def test_phrase_map_without_the_language_is_skipped(self):
        rule = {"id": "house", "kind": "phrases", "severity": "info", "phrases": {"en": ["utilize"]}}
        report = lint.lint("Dùng nó.", lang_code="vi", rules=[rule])
        self.assertEqual([s["rule"] for s in report["skipped"]], ["house"])

    def test_malformed_rules_are_rejected(self):
        bad = [
            [{"kind": "phrases"}],
            [{"id": "x", "kind": "magic", "severity": "warn"}],
            [{"id": "x", "kind": "phrases", "severity": "error", "phrases": ["a"]}],
            [{"id": "x", "kind": "phrases", "severity": "warn"}],
            [{"id": "x", "kind": "density", "severity": "warn"}],
        ]
        for rules in bad:
            with tempfile.TemporaryDirectory() as tmp:
                self.write_rules(tmp, "bad.json", rules)
                with self.assertRaises(lint.LintError, msg=rules):
                    lint.load_rules(tmp)

    def test_missing_directory_is_rejected(self):
        with self.assertRaises(lint.LintError):
            lint.load_rules("does-not-exist")

    def test_every_pack_with_connectors_lists_strings(self):
        for code in lang.available():
            self.assertTrue(all(isinstance(c, str) and c for c in lang.load(code)["connectors"]), code)


class CliTest(unittest.TestCase):
    """``pe lint`` prints JSON and exits 0 even with findings; bad rule files exit 2."""

    def run_pe(self, *args):
        """Run ``pe lint`` with ``args``; return the exit code and parsed JSON."""
        proc = subprocess.run([sys.executable, str(PE), "lint", *args], capture_output=True,
                              text=True, encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout) if proc.stdout else None

    def test_findings_do_not_fail(self):
        code, report = self.run_pe("--text", "However, a. However, b.", "--lang", "en")
        self.assertEqual(code, 0)
        self.assertEqual(report["counts"]["warn"], 1)

    def test_original_from_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "original.txt")
            path.write_text("Giá tăng.", encoding="utf-8")
            code, report = self.run_pe("--text", "Ngoài ra, giá tăng.", "--original", str(path))
        self.assertEqual((code, report["lang"]), (0, "vi"))
        self.assertIn("connector_added", [f["rule"] for f in report["findings"]])

    def test_bad_rules_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bad.json").write_text("{", encoding="utf-8")
            code, report = self.run_pe("--text", "Hi.", "--rules", tmp)
        self.assertEqual(code, 2)
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()
