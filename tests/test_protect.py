import json
import subprocess
import sys
import unittest

import _path  # noqa: F401
from paraphrase_everything.protect import ProtectError, protect, restore

PE = str(_path.SCRIPTS / "pe.py")


def masked_types(text, keep=()):
    _, mapping = protect(text, keep)
    return [(v["type"], v["text"]) for v in mapping["placeholders"].values()]


class SpanTypesTest(unittest.TestCase):
    def test_code_block(self):
        text = "Intro\n```python\nprint('hi')\n```\nOutro"
        masked, _ = protect(text)
        self.assertEqual(masked, "Intro\n⟦P1⟧\nOutro")

    def test_unclosed_code_block_runs_to_end(self):
        self.assertEqual(masked_types("a\n~~~\ncode")[0][0], "code_block")

    def test_inline_code(self):
        self.assertEqual(masked_types("Run `pip install x` now."),
                         [("inline_code", "`pip install x`")])
        self.assertEqual(masked_types("Use ``a ` b`` here."),
                         [("inline_code", "``a ` b``")])

    def test_latex(self):
        self.assertEqual(masked_types("Energy $E = mc^2$ holds."),
                         [("latex_inline", "$E = mc^2$")])
        self.assertEqual(masked_types("See $$\\int f$$."), [("latex_block", "$$\\int f$$")])

    def test_currency_is_not_latex(self):
        self.assertEqual(masked_types("It costs $5 and $10."), [])

    def test_html(self):
        self.assertEqual(masked_types("A <b>bold</b> word<!-- note -->."),
                         [("html_tag", "<b>"), ("html_tag", "</b>"), ("html_comment", "<!-- note -->")])
        self.assertEqual(masked_types("if a < b and c > d"), [])

    def test_link_target_keeps_link_text(self):
        masked, _ = protect('Read [the docs](https://x.io/a "Title") first.')
        self.assertEqual(masked, "Read [the docs](⟦P1⟧) first.")

    def test_url_trailing_punctuation(self):
        self.assertEqual(masked_types("Visit https://example.com/path."),
                         [("url", "https://example.com/path")])

    def test_email(self):
        self.assertEqual(masked_types("Mail me at a.b@example.co.jp today."),
                         [("email", "a.b@example.co.jp")])

    def test_keep_terms_longest_first_and_word_bounded(self):
        types = masked_types("New York City is not New Yorker.", keep=["New York", "New York City"])
        self.assertEqual(types, [("keep", "New York City")])

    def test_numbers_and_names_are_not_masked(self):
        self.assertEqual(masked_types("Alice grew revenue by 42% in 2024 [1]."), [])

    def test_vietnamese_and_japanese_context(self):
        masked, _ = protect("Chạy lệnh `npm test` để kiểm tra.")
        self.assertEqual(masked, "Chạy lệnh ⟦P1⟧ để kiểm tra.")
        masked, _ = protect("詳細はhttps://example.jp/を参照。")
        self.assertEqual(masked, "詳細は⟦P1⟧を参照。")

    def test_rejects_existing_placeholders(self):
        with self.assertRaises(ProtectError):
            protect("already ⟦P1⟧ here")


class RoundTripTest(unittest.TestCase):
    SAMPLE = ("# Title\r\n\r\nSee `x` and https://a.io, $a+b$.\r\n"
              "```\r\ncode\r\n```\r\n<i>hi</i> [l](u)\r\n")

    def test_identity_round_trip(self):
        masked, mapping = protect(self.SAMPLE)
        restored, report = restore(masked, mapping)
        self.assertEqual(restored, self.SAMPLE)
        self.assertTrue(report["ok"])
        self.assertEqual(report["restored"], report["total"])

    def test_reordered_placeholders_restore(self):
        masked, mapping = protect("Use `a` then `b`.")
        restored, report = restore("First ⟦P2⟧, then ⟦ P1 ⟧.", mapping)
        self.assertEqual(restored, "First `b`, then `a`.")
        self.assertTrue(report["ok"])

    def test_missing_duplicated_unknown(self):
        _, mapping = protect("Use `a` then `b`.")
        restored, report = restore("⟦P1⟧ ⟦P1⟧ ⟦P9⟧", mapping)
        self.assertEqual(restored, "`a` `a` ⟦P9⟧")
        self.assertFalse(report["ok"])
        kinds = sorted(i["type"] for i in report["issues"])
        self.assertEqual(kinds, ["placeholder_duplicated", "placeholder_missing", "placeholder_unknown"])


class CliTest(unittest.TestCase):
    def run_pe(self, *args, stdin=None):
        proc = subprocess.run([sys.executable, PE, *args], input=stdin, capture_output=True,
                              text=True, encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout)

    def test_protect_restore_via_stdin_and_files(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            mp = os.path.join(d, "map.json")
            code, out = self.run_pe("protect", "-", "--map", mp, stdin="Gõ `ls` nhé")
            self.assertEqual((code, out["text"]), (0, "Gõ ⟦P1⟧ nhé"))
            code, out = self.run_pe("restore", "--text", "Hãy gõ ⟦P1⟧", "--map", mp)
            self.assertEqual((code, out["text"]), (0, "Hãy gõ `ls`"))
            code, out = self.run_pe("restore", "--text", "mất rồi", "--map", mp)
            self.assertEqual(code, 1)
            self.assertFalse(out["ok"])

    def test_detect_and_langs(self):
        self.assertEqual(self.run_pe("detect", "--text", "Xin chào các bạn")[1]["lang"], "vi")
        codes = [l["code"] for l in self.run_pe("langs")[1]["langs"]]
        self.assertTrue({"en", "ja", "vi", "zh"} <= set(codes))


if __name__ == "__main__":
    unittest.main()
