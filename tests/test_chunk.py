"""Tests for chunking, merging, and the shared glossary (story 003)."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import chunk, cli, glossary
from paraphrase_everything.protect import PLACEHOLDER_RE, protect

def run(argv):
    """Run the CLI with its JSON output discarded; return the exit code."""
    with contextlib.redirect_stdout(io.StringIO()):
        return cli.main(argv)


def read(path):
    """Read a UTF-8 file keeping line endings."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


DOC = ("# Intro\n\n" + "The NASA team met Alice Smith. " * 6 +
       "\n\n## Part 2\n\n- item one\n- item two\n\n```py\nx = 1\n\ny = 2\n```\n\n" +
       "Another sentence here. " * 30 + "\n\n# End\n\nBye.\n")


class SplitTest(unittest.TestCase):
    """Splitting is lossless and respects structure."""

    def test_below_threshold_is_one_chunk(self):
        chunks, info = chunk.split("Short text.\n", max_words=5)
        self.assertEqual(chunks, ["Short text.\n"])
        self.assertFalse(info["needs_chunking"])

    def test_empty_input(self):
        self.assertEqual(chunk.split("")[0], [])

    def test_roundtrip_exact(self):
        for text in (DOC, DOC.replace("\n", "\r\n"), DOC.rstrip("\n")):
            chunks, info = chunk.split(text, max_words=40, threshold=10)
            self.assertGreater(len(chunks), 1)
            self.assertEqual("".join(chunks), text)

    def test_chunks_respect_budget_and_headings(self):
        chunks, _ = chunk.split(DOC, max_words=45, threshold=10)
        for c in chunks:
            self.assertLessEqual(chunk.size(c), 45)
            self.assertFalse(c.rstrip().splitlines()[-1].startswith("#"), "ends on a bare heading")
        self.assertTrue(any(c.startswith("## Part 2") for c in chunks))

    def test_code_fence_and_list_items_not_split(self):
        chunks, _ = chunk.split(DOC, max_words=8, threshold=10)
        fence = "```py\nx = 1\n\ny = 2\n```"
        self.assertEqual(sum(fence in c for c in chunks), 1)
        for item in ("- item one\n", "- item two\n"):
            self.assertEqual(sum(item in c for c in chunks), 1)

    def test_never_cuts_inside_a_sentence(self):
        text = "First one is here. Second one is here.\n" + "Third sentence goes on. " * 40
        chunks, _ = chunk.split(text, max_words=20, threshold=5)
        for c in chunks:
            self.assertTrue(c.rstrip().endswith("."), repr(c))

    def test_placeholders_never_split(self):
        source = "Call `foo()` then visit https://example.com/a and `bar()`. " * 40
        masked, _ = protect(source)
        chunks, _ = chunk.split(masked, max_words=15, threshold=5)
        self.assertGreater(len(chunks), 2)
        for c in chunks:
            self.assertEqual(c.count("⟦"), c.count("⟧"))
            self.assertEqual(c.count("⟦"), len(PLACEHOLDER_RE.findall(c)))

    def test_cjk_size_and_split(self):
        text = "これは日本語の文章です。" * 400
        self.assertGreater(chunk.size(text), 1000)
        chunks, info = chunk.split(text, max_words=600, threshold=1000)
        self.assertTrue(info["needs_chunking"])
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(c.endswith("。") for c in chunks))


class MergeTest(unittest.TestCase):
    """Chunk files merge back to the original, or to rewritten copies."""

    def _write(self, tmp):
        """Write DOC chunks into ``tmp/chunks`` and return that path."""
        chunks, info = chunk.split(DOC, max_words=40, threshold=10)
        out = Path(tmp) / "chunks"
        chunk.write_chunks(chunks, info, out)
        return out

    def test_merge_of_unchanged_chunks_equals_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(chunk.merge(self._write(tmp)), DOC)

    def test_merge_rewritten_keeps_paragraph_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._write(tmp)
            rewritten = Path(tmp) / "rw"
            rewritten.mkdir()
            for f in out.glob("*.md"):
                text = read(f).rstrip() + " "
                (rewritten / f.name).write_text(text, encoding="utf-8", newline="")
            merged = chunk.merge(out, rewritten)
            self.assertEqual(merged.count("\n\n"), DOC.count("\n\n"))

    def test_missing_files_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self._write(tmp)
            empty = Path(tmp) / "none"
            empty.mkdir()
            with self.assertRaises(chunk.ChunkError):
                chunk.merge(out, empty)
            with self.assertRaises(chunk.ChunkError):
                chunk.merge(empty)

    def test_cli_chunk_and_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.md"
            src.write_text(DOC, encoding="utf-8", newline="")
            out, merged = Path(tmp) / "c", Path(tmp) / "m.md"
            self.assertEqual(run(["chunk", str(src), "-o", str(out), "--max-words", "40",
                                       "--threshold", "10"]), 0)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["needs_chunking"])
            self.assertEqual(run(["merge", str(out), "-o", str(merged)]), 0)
            self.assertEqual(read(merged), DOC)


class GlossaryTest(unittest.TestCase):
    """Term extraction and verification."""

    def test_extract_kinds_and_decisions(self):
        entries = {e["term"]: e for e in glossary.extract(DOC)}
        self.assertEqual(entries["NASA"]["kind"], "acronym")
        self.assertEqual(entries["Alice Smith"]["decision"], "keep")
        self.assertNotIn("Another", entries)
        self.assertNotIn("The", entries)

    def test_katakana_and_vietnamese_names(self):
        ja = glossary.extract("サーバーを再起動する。サーバーは安全です。")
        self.assertEqual(ja[0]["term"], "サーバー")
        self.assertEqual(ja[0]["decision"], "rewrite-consistently")
        vi = glossary.extract("Anh gặp Nguyễn Văn An ở Hà Nội. Sau đó Nguyễn Văn An về nhà.")
        self.assertIn("Nguyễn Văn An", {e["term"] for e in vi})

    def test_placeholders_and_rare_terms_skipped(self):
        entries = glossary.extract("Only once Zed. ⟦P1⟧ and ⟦P1⟧ again.")
        self.assertEqual(entries, [])

    def test_keep_and_term_options(self):
        entries = {e["term"]: e for e in
                   glossary.extract("one thing, one thing.", keep=["Acme"], terms=["thing"])}
        self.assertEqual(entries["Acme"]["decision"], "keep")
        self.assertEqual(entries["thing"]["decision"], "rewrite-consistently")

    def test_parse_validation(self):
        with self.assertRaises(glossary.GlossaryError):
            glossary.parse({"term": "x"})
        with self.assertRaises(glossary.GlossaryError):
            glossary.parse([{"term": "x", "decision": "maybe"}])
        self.assertEqual(len(glossary.parse([{"term": "x", "decision": "keep"}])), 1)

    def test_verify_reports_problems(self):
        entries = [
            {"term": "NASA", "decision": "keep"},
            {"term": "server", "decision": "rewrite-consistently", "rendering": "host"},
            {"term": "cache", "decision": "rewrite-consistently"},
        ]
        report = glossary.verify("NASA runs the server. NASA likes cache.",
                                 "The agency runs the server.", entries)
        kinds = {w["type"] for w in report["warnings"]}
        self.assertEqual(kinds, {"term_lost", "term_leftover", "rendering_unused", "rendering_missing"})
        self.assertFalse(report["ok"])
        good = glossary.verify("NASA runs the server.", "NASA runs the host.", entries[:2])
        self.assertTrue(good["ok"])

    def test_cli_extract_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, rw, gl = (Path(tmp) / n for n in ("a.txt", "b.txt", "g.json"))
            src.write_text("NASA and NASA.", encoding="utf-8")
            rw.write_text("NASA only.", encoding="utf-8")
            self.assertEqual(run(["glossary", str(src), "-o", str(gl)]), 0)
            self.assertEqual(run(["glossary", str(src), "--glossary", str(gl),
                                       "--rewritten", str(rw)]), 1)


if __name__ == "__main__":
    unittest.main()
