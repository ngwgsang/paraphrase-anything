import re
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import lang

REQUIRED_KEYS = {
    "code", "name", "length_unit", "match", "sentence_terminators", "abbreviations",
    "negation_markers", "hedge_markers", "decimal_separator", "thousands_separator", "cliches",
}


class LangDataTest(unittest.TestCase):
    def test_available(self):
        self.assertTrue({"en", "ja", "vi", "zh"} <= set(lang.available()))

    def test_every_pack_has_required_keys(self):
        for code in lang.available() + [lang.DEFAULT]:
            data = lang.load(code)
            self.assertTrue(REQUIRED_KEYS <= data.keys(), code)
            self.assertIn(data["length_unit"], ("word", "char"))
            self.assertIn(data["match"], ("word", "substring"))

    def test_unknown_language_falls_back(self):
        data = lang.load("xx")
        self.assertFalse(data["supported"])
        self.assertEqual(data["negation_markers"], [])
        self.assertTrue(lang.load("vi")["supported"])

    def test_no_language_literals_in_code(self):
        """Story 012 phase 1: markers live in JSON, never in Python code."""
        pkg = Path(_path.SCRIPTS) / "paraphrase_everything"
        markers = set()
        for code in lang.available():
            data = lang.load(code)
            markers.update(data["negation_markers"] + data["hedge_markers"])
        for py in pkg.rglob("*.py"):
            strings = re.findall(r"[\"']([^\"'\n]+)[\"']", py.read_text(encoding="utf-8"))
            leaked = markers & set(strings)
            self.assertFalse(leaked, f"{py.name} hard-codes {leaked}")


class DetectTest(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(lang.detect("The quick brown fox."), "en")
        self.assertEqual(lang.detect("Hôm nay trời đẹp quá."), "vi")
        self.assertEqual(lang.detect("今日はいい天気ですね。"), "ja")
        self.assertEqual(lang.detect("今天天气很好"), "zh")
        self.assertEqual(lang.detect("東京都の天気は晴れです。"), "ja")  # kana outranks Han
        self.assertEqual(lang.detect("Привет, как дела?"), lang.DEFAULT)  # no pack claims Cyrillic
        self.assertEqual(lang.detect("The word 今天 means today."), "en")
        self.assertEqual(lang.detect("12345"), lang.DEFAULT)


if __name__ == "__main__":
    unittest.main()
