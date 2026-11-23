"""Tests for format-preserving I/O: text, Markdown, SRT, VTT (story 006)."""

import contextlib
import io as stdlib_io
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import cli
from paraphrase_everything import io as formats

MD = """---
title: Notes
---

# Heading one

Para line one
continues here.

- item one
  wrapped line
- [ ] task two

> quoted a
> quoted b

```py
code = 1

more = 2
```

| a | b |
|---|---|
| 1 | 2 |

    indented code

<div>
html block
</div>

[ref]: http://example.com
Final para with `code` and https://example.com/x.
"""

SRT = ("1\r\n00:00:01,000 --> 00:00:03,000\r\nHello there\r\nmy friend\r\n\r\n"
       "2\r\n00:00:04,000 --> 00:00:04,500\r\nBye\r\n")

VTT = ("WEBVTT\n\nNOTE a comment\n\nintro\n00:00:01.000 --> 00:00:03.000 align:start\nHello there\n\n"
       "00:03.000 --> 00:04.000\nSecond cue\n")

TEXT = "  Indented first line\n  second line\n\n\nNext paragraph.\n"


def upper(segments):
    """Map each segment id to its upper-cased text."""
    return {s["id"]: s["text"].upper() for s in segments}


def run(argv):
    """Run the CLI with its JSON output discarded; return the exit code."""
    with contextlib.redirect_stdout(stdlib_io.StringIO()):
        return cli.main(argv)


def read(path):
    """Read a UTF-8 file keeping line endings."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


class RoundTripTest(unittest.TestCase):
    """Unchanged documents come back byte-equal; edits touch only segment spans."""

    def test_unchanged_roundtrip_is_byte_equal(self):
        for fmt, source in (("text", TEXT), ("markdown", MD), ("srt", SRT), ("vtt", VTT),
                            ("text", TEXT.replace("\n", "\r\n")), ("markdown", MD.replace("\n", "\r\n")),
                            ("text", ""), ("markdown", "")):
            segments = formats.extract(source, fmt)
            self.assertEqual(formats.rebuild(source, fmt, {}), source, fmt)
            same = {s["id"]: s["text"] for s in segments}
            self.assertEqual(formats.rebuild(source, fmt, same), source, fmt)

    def test_mixed_line_endings_survive_when_unchanged(self):
        source = "One\r\ntwo\n\nThree\r\n"
        segments = formats.extract(source, "text")
        out = formats.rebuild(source, "text", {segments[1]["id"]: "THREE"})
        self.assertEqual(out, "One\r\ntwo\n\nTHREE\r\n")

    def test_crlf_kept_when_rewrite_has_new_lines(self):
        source = "Alpha beta\r\n\r\nGamma\r\n"
        out = formats.rebuild(source, "text", {1: "Alpha\nbeta two"})
        self.assertEqual(out, "Alpha\r\nbeta two\r\n\r\nGamma\r\n")

    def test_unknown_and_empty_segments_rejected(self):
        with self.assertRaises(formats.FormatError):
            formats.rebuild(TEXT, "text", {99: "x"})
        with self.assertRaises(formats.FormatError):
            formats.rebuild(TEXT, "text", {1: "  "})
        with self.assertRaises(formats.FormatError):
            formats.extract(TEXT, "docx")


class TextTest(unittest.TestCase):
    """Plain text segments are paragraphs."""

    def test_paragraph_segments_and_indentation(self):
        segments = formats.extract(TEXT, "text")
        self.assertEqual([s["text"] for s in segments],
                         ["Indented first line\n  second line", "Next paragraph."])
        out = formats.rebuild(TEXT, "text", {2: "Next one."})
        self.assertEqual(out, "  Indented first line\n  second line\n\n\nNext one.\n")


class MarkdownTest(unittest.TestCase):
    """Only prose blocks are segments."""

    def setUp(self):
        self.segments = formats.extract(MD, "markdown")

    def test_prose_only(self):
        self.assertEqual([s["text"] for s in self.segments], [
            "Heading one", "Para line one\ncontinues here.", "item one\nwrapped line", "task two",
            "quoted a\nquoted b", "Final para with `code` and https://example.com/x."])

    def test_rebuild_leaves_structure_untouched(self):
        out = formats.rebuild(MD, "markdown", upper(self.segments))
        for kept in ("---\ntitle: Notes\n---", "```py\ncode = 1\n\nmore = 2\n```", "| a | b |\n|---|---|",
                     "    indented code", "<div>\nhtml block\n</div>", "[ref]: http://example.com"):
            self.assertIn(kept, out)
        for changed in ("# HEADING ONE", "- ITEM ONE\n  WRAPPED LINE", "- [ ] TASK TWO",
                        "> QUOTED A\n> QUOTED B"):
            self.assertIn(changed, out)

    def test_new_lines_reuse_continuation_prefix(self):
        out = formats.rebuild(MD, "markdown", {4: "one\ntwo"})
        self.assertNotIn("task two", out)
        self.assertIn("- [ ] one\n", out)
        out = formats.rebuild(MD, "markdown", {3: "first\nsecond\nthird"})
        self.assertIn("- first\n  second\n  third\n", out)
        out = formats.rebuild(MD, "markdown", {5: "a\nb\nc"})
        self.assertIn("> a\n> b\n> c\n", out)

    def test_closing_hashes_and_trailing_text_kept(self):
        out = formats.rebuild("## Title ##\n\nBody\n", "markdown", {1: "New"})
        self.assertEqual(out, "## New ##\n\nBody\n")

    def test_unclosed_front_matter_is_prose(self):
        segments = formats.extract("---\nnot front matter\n", "markdown")
        self.assertEqual(len(segments), 1)


class SubtitleTest(unittest.TestCase):
    """Only cue text changes; timing is never touched."""

    def test_srt_cues(self):
        segments = formats.extract(SRT, "srt")
        self.assertEqual([s["text"] for s in segments], ["Hello there\nmy friend", "Bye"])
        out = formats.rebuild(SRT, "srt", upper(segments))
        self.assertEqual(out, SRT.replace("Hello there\r\nmy friend", "HELLO THERE\r\nMY FRIEND")
                         .replace("Bye", "BYE"))

    def test_vtt_skips_header_note_and_identifier(self):
        segments = formats.extract(VTT, "vtt")
        self.assertEqual([s["text"] for s in segments], ["Hello there", "Second cue"])
        out = formats.rebuild(VTT, "vtt", {1: "Hi", 2: "Next"})
        self.assertIn("WEBVTT\n\nNOTE a comment\n\nintro\n00:00:01.000 --> 00:00:03.000 align:start\nHi\n", out)

    def test_timing_lines_identical_after_rewrite(self):
        out = formats.rebuild(SRT, "srt", {1: "Totally different words", 2: "See you"})
        timing = [l for l in out.splitlines() if "-->" in l]
        self.assertEqual(timing, [l for l in SRT.splitlines() if "-->" in l])

    def test_structure_breaking_text_rejected(self):
        with self.assertRaises(formats.FormatError):
            formats.rebuild(SRT, "srt", {1: "a\n\nb"})
        with self.assertRaises(formats.FormatError):
            formats.rebuild(SRT, "srt", {1: "00:00:01,000 --> 00:00:02,000"})

    def test_lint_limits(self):
        limits = {"max_line_chars": 10, "max_cps": 5}
        kinds = {(w["type"], w["cue"]) for w in formats.srt.lint(SRT, limits)}
        self.assertEqual(kinds, {("line_too_long", 1), ("reading_speed", 1), ("reading_speed", 2)})
        self.assertEqual(formats.srt.lint(SRT, {"max_line_chars": None, "max_cps": None}), [])


class DetectTest(unittest.TestCase):
    """Format detection by extension, then content."""

    def test_extension_wins(self):
        self.assertEqual(formats.detect("plain", "a.md"), "markdown")
        self.assertEqual(formats.detect("# h", "a.txt"), "text")
        self.assertEqual(formats.detect("x", "a.SRT"), "srt")

    def test_content_detection(self):
        self.assertEqual(formats.detect(VTT), "vtt")
        self.assertEqual(formats.detect(SRT), "srt")
        self.assertEqual(formats.detect(MD), "markdown")
        self.assertEqual(formats.detect("Just some words.\n\nAnd more."), "text")
        self.assertEqual(formats.detect("See [docs](http://x.y) for **more**."), "markdown")


class CliTest(unittest.TestCase):
    """The extract and rebuild commands."""

    def test_extract_edit_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, seg, out = (Path(tmp) / n for n in ("in.md", "seg.json", "out.md"))
            src.write_text(MD.replace("\n", "\r\n"), encoding="utf-8", newline="")
            self.assertEqual(run(["extract", str(src), "-o", str(seg)]), 0)
            data = json.loads(read(seg))
            self.assertEqual(data["format"], "markdown")
            for item in data["segments"]:
                item["text"] = item["text"].upper()
            seg.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(run(["rebuild", str(src), "--segments", str(seg), "-o", str(out)]), 0)
            self.assertIn("# HEADING ONE\r\n", read(out))
            self.assertIn("```py\r\ncode = 1\r\n\r\nmore = 2\r\n```", read(out))

    def test_rebuild_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            seg = Path(tmp) / "seg.json"
            seg.write_text('[{"id": 99, "text": "x"}]', encoding="utf-8")
            self.assertEqual(run(["rebuild", "--text", "Hello.", "--segments", str(seg)]), 2)
            seg.write_text('{"nope": 1}', encoding="utf-8")
            self.assertEqual(run(["rebuild", "--text", "Hello.", "--segments", str(seg)]), 2)

    def test_srt_rebuild_reports_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, seg = Path(tmp) / "in.srt", Path(tmp) / "seg.json"
            src.write_text(SRT, encoding="utf-8", newline="")
            seg.write_text('[{"id": 1, "text": "A very long subtitle line indeed, far beyond limits"}]',
                           encoding="utf-8")
            buffer = stdlib_io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = cli.main(["rebuild", str(src), "--segments", str(seg)])
            result = json.loads(buffer.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(result["changed"], 1)
            self.assertIn("line_too_long", {w["type"] for w in result["warnings"]})
            self.assertEqual(result["text"].count("-->"), 2)

    def test_subtitle_defaults_come_from_language_data(self):
        from paraphrase_everything import lang
        self.assertEqual(lang.load("en")["subtitle"]["max_line_chars"], 42)
        self.assertLess(lang.load("ja")["subtitle"]["max_line_chars"], 42)


if __name__ == "__main__":
    unittest.main()
