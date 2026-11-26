"""Tests for localization files: JSON and gettext PO (story 031)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import check, harness, io, protect
from paraphrase_everything.io import base

PE = Path(__file__).resolve().parent.parent / "skills" / "paraphrase-anything" / "scripts" / "pe.py"

LOCALE = """{
  "nav": {"home": "Home", "help": "Ayuda y soporte técnico"},
  "msg": {
    "saved": "Đã lưu tất cả thay đổi của bạn.",
    "count": "{count, plural, one {# file} other {# files}} were uploaded today",
    "quote": "Say \\"hi\\" to\\nthe team."
  },
  "list": ["ファイルをアップロードできませんでした。", 3, null]
}
"""

CATALOG = """msgid ""
msgstr ""
"Language: vi\\n"

#. translator note
#: app.py:3
msgid "Saved"
msgstr "Đã lưu tất cả các thay đổi của bạn."

msgctxt "menu"
msgid "Open"
msgstr "Mở"

msgid "One file"
msgid_plural "%d files"
msgstr[0] "Đã tải lên %d tệp tin"
"""

TEMPLATE = """msgid ""
msgstr ""

msgid "Your changes were saved."
msgstr ""

msgid "Delete %(name)s permanently?"
msgstr ""
"""


class JsonTest(unittest.TestCase):
    """String values are segments; keys and every other byte stay."""

    def test_values_with_key_paths(self):
        segs = io.extract(LOCALE, "json")
        self.assertEqual([s["context"] for s in segs],
                         ["nav.help", "msg.saved", "msg.count", "msg.quote", "list.0"])
        self.assertEqual(segs[3]["text"], 'Say "hi" to\nthe team.')

    def test_short_values_are_listed_as_skipped(self):
        self.assertEqual(io.skipped(LOCALE, "json"), [{"context": "nav.home", "text": "Home",
                                                       "why": "a single short word"}])

    def test_keys_option_limits_the_paths(self):
        segs = io.extract(LOCALE, "json", ["keys=msg.*"])
        self.assertEqual([s["context"] for s in segs], ["msg.saved", "msg.count", "msg.quote"])

    def test_rebuild_escapes_and_keeps_layout(self):
        out = io.rebuild(LOCALE, "json", {4: 'Tell the "team"\nhello.', 2: "Mọi thay đổi đã được lưu."})
        data = json.loads(out)
        self.assertEqual(data["msg"]["quote"], 'Tell the "team"\nhello.')
        self.assertEqual(data["msg"]["saved"], "Mọi thay đổi đã được lưu.")
        self.assertIn('"saved": "Mọi thay đổi đã được lưu."', out)  # no \\u escapes added
        self.assertEqual(out.replace('"Mọi thay đổi đã được lưu."', '"Đã lưu tất cả thay đổi của bạn."')
                         .replace('"Tell the \\"team\\"\\nhello."', '"Say \\"hi\\" to\\nthe team."'), LOCALE)

    def test_ascii_escaped_source_stays_ascii(self):
        source = '{"a": "Caf\\u00e9 is open now"}'
        self.assertEqual(io.rebuild(source, "json", {1: "Café opens now"}), '{"a": "Caf\\u00e9 opens now"}')

    def test_rejects_invalid_or_scalar_json(self):
        for source in ('{"a": ', '"just a string"', "42"):
            with self.assertRaises(io.FormatError, msg=source):
                io.extract(source, "json")

    def test_bom_is_kept(self):
        source = '﻿{"a": "Hello there, friend."}'
        self.assertEqual(io.rebuild(source, "json", {1: "Hi there, friend."}), '﻿{"a": "Hi there, friend."}')


class PoTest(unittest.TestCase):
    """Translations are segments; ids, context, comments, and the header stay."""

    def test_translations_with_their_source(self):
        segs = io.extract(CATALOG, "po")
        self.assertEqual([(s["text"], s["context"]) for s in segs],
                         [("Đã lưu tất cả các thay đổi của bạn.", "Saved"), ("Đã tải lên %d tệp tin", "One file")])
        self.assertEqual(io.skipped(CATALOG, "po"), [{"context": "Open", "text": "Mở", "why": "a single short word"}])

    def test_template_rewrites_msgid(self):
        segs = io.extract(TEMPLATE, "po")
        self.assertEqual([s["text"] for s in segs], ["Your changes were saved.", "Delete %(name)s permanently?"])
        out = io.rebuild(TEMPLATE, "po", {1: "All your changes are saved."})
        self.assertIn('msgid "All your changes are saved."\nmsgstr ""', out)
        self.assertTrue(out.startswith('msgid ""\nmsgstr ""\n'))

    def test_rebuild_keeps_everything_else(self):
        out = io.rebuild(CATALOG, "po", {1: 'Mọi "thay đổi" đã được lưu.'})
        self.assertEqual(out, CATALOG.replace('"Đã lưu tất cả các thay đổi của bạn."', '"Mọi \\"thay đổi\\" đã được lưu."'))
        self.assertEqual(io.extract(out, "po")[0]["text"], 'Mọi "thay đổi" đã được lưu.')

    def test_multi_line_field_is_written_back_over_lines(self):
        source = 'msgid "Help"\nmsgstr ""\n"First line of help.\\n"\n"Second line of help."\n'
        out = io.rebuild(source, "po", {1: "Line one here.\nLine two here.\nLine three."})
        self.assertEqual(out, 'msgid "Help"\nmsgstr ""\n"Line one here.\\n"\n"Line two here.\\n"\n"Line three."\n')

    def test_crlf_catalog(self):
        source = CATALOG.replace("\n", "\r\n")
        out = io.rebuild(source, "po", {2: "Đã tải %d tệp lên xong"})
        self.assertNotIn("\n", out.replace("\r\n", ""))
        self.assertIn('msgstr[0] "Đã tải %d tệp lên xong"\r\n', out)

    def test_malformed_line_is_rejected(self):
        with self.assertRaises(io.FormatError):
            io.extract('msgid "a"\nmsgstr oops\n', "po")


class PlaceholderTest(unittest.TestCase):
    """Interpolation placeholders are protected spans, so dropping one is a check error."""

    def test_each_kind_is_protected(self):
        for token in ("{name}", "{{ user.name }}", "%{count}", "{0}", "%s", "%d", "%1$s", "%(name)s", "%@",
                      "{count, plural, one {# item} other {# items}}", "{g, select, f {she} other {they}}"):
            text = f"Hello {token} there"
            spans = [text[s:e] for s, e, _ in protect.find_spans(text)]
            self.assertEqual(spans, [token], token)

    def test_percent_in_prose_is_not_a_placeholder(self):
        for text in ("Sales rose 50% of the time.", "It is 100%s", "a 5% discount"):
            self.assertEqual(protect.find_spans(text), [], text)

    def test_dropped_placeholder_is_an_error(self):
        for lang, original, rewrite in (
                ("en", "You have {count} new messages.", "There are new messages."),
                ("vi", "Bạn có %d tin nhắn mới.", "Bạn có tin nhắn mới."),
                ("ja", "%(name)sさん、ようこそ。", "ようこそ。")):
            errors = check.check(original, rewrite, lang_code=lang)["errors"]
            self.assertEqual([e["type"] for e in errors], ["protected_span_missing"], lang)

    def test_worth_rewriting(self):
        self.assertIsNone(base.worth_rewriting("Save your work before leaving."))
        self.assertIsNone(base.worth_rewriting("ファイルをアップロードできませんでした。"))
        self.assertEqual(base.worth_rewriting("Save"), "a single short word")
        self.assertEqual(base.worth_rewriting("{count}"), "only placeholders or markup")
        self.assertEqual(base.worth_rewriting(" "), "empty")
        self.assertEqual(base.worth_rewriting("—"), "no words")


class RouteTest(unittest.TestCase):
    """A locale file runs through a harness Files session and through ``pe extract``."""

    def test_harness_session_rebuilds_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = harness.init(LOCALE, Path(tmp) / "s", fmt="json", format_options=["keys=msg.*"], preset="fast")
            self.assertEqual(state["format_options"], {"keys": ["msg.*"]})
            self.assertEqual(state["segments"], 3)
            task = harness.next_task(state["session_dir"])
            masked = Path(task["inputs"]["previous"]).read_text(encoding="utf-8")
            Path(task["output"]).write_text(masked.replace("Đã lưu tất cả thay đổi của bạn.", "Mọi thay đổi đã được lưu."),
                                            encoding="utf-8")
            self.assertTrue(harness.submit(state["session_dir"])["ok"])
            done = harness.next_task(state["session_dir"])
            out = Path(done["output"])
            self.assertEqual(out.suffix, ".json")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["msg"]["saved"], "Mọi thay đổi đã được lưu.")

    def test_crlf_line_break_inside_a_block_is_not_a_blank_line(self):
        from paraphrase_everything import routes
        text = "First.\r\n\r\nSay hi to\r\nthe team.\r\n \r\nLast."
        self.assertEqual(routes.blocks(text), ["First.", "Say hi to\r\nthe team.", "Last."])

    def test_cli_extract_lists_context_and_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "vi.po")
            path.write_text(CATALOG, encoding="utf-8")
            proc = subprocess.run([sys.executable, str(PE), "extract", str(path)], capture_output=True,
                                  text=True, encoding="utf-8")
        out = json.loads(proc.stdout)
        self.assertEqual((proc.returncode, out["format"], out["count"]), (0, "po", 2))
        self.assertEqual(out["segments"][0]["context"], "Saved")
        self.assertEqual(out["skipped"][0]["text"], "Mở")


if __name__ == "__main__":
    unittest.main()
