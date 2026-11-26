"""Tests for the self-registering format registry and the shared format contract (story 029)."""

import json
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import _path  # noqa: F401
from paraphrase_everything import harness, io, routes

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = Path(__file__).resolve().parent / "format_samples"
IO_DIR = ROOT / "skills" / "paraphrase-anything" / "scripts" / "paraphrase_everything" / "io"
PE = ROOT / "skills" / "paraphrase-anything" / "scripts" / "pe.py"
FORMATS_MD = ROOT / "skills" / "paraphrase-anything" / "references" / "formats.md"


def fake_module(name="fake", **spec):
    """A throwaway format module: one segment per line, with an optional ``upper`` option."""
    module = types.ModuleType(f"fake_{name}")

    def extract(source, upper=False):
        """One segment per non-empty line."""
        segs, pos = [], 0
        for line in source.split("\n"):
            if line:
                segs.append({"id": len(segs) + 1, "text": line.upper() if upper else line,
                             "start": pos, "end": pos + len(line), "cont_prefix": ""})
            pos += len(line) + 1
        return segs

    def rebuild(source, rewritten, upper=False):
        """Replace whole lines by id."""
        lines = [ln for ln in source.split("\n")]
        ids = [i for i, ln in enumerate(lines) if ln]
        for seg_id, text in rewritten.items():
            lines[ids[seg_id - 1]] = text
        return "\n".join(lines)

    module.extract, module.rebuild = extract, rebuild
    module.SPECS = [dict({"name": name, "extensions": [f".{name}"], "output": f".{name}",
                          "sniff": lambda s: s.startswith("FAKE"), "priority": 99,
                          "options": {"upper": {"type": "bool", "help": "upper-case the segments"}}}, **spec)]
    return module


def skeleton(source, segments):
    """The text outside every segment span, in order."""
    parts, pos = [], 0
    for seg in segments:
        parts.append(source[pos:seg["start"]])
        pos = seg["end"]
    return parts + [source[pos:]]


class RegistryTest(unittest.TestCase):
    """Formats, extensions, detection order, and outputs are derived from module specs."""

    def test_every_module_in_the_package_is_registered(self):
        modules = sorted(p.stem for p in IO_DIR.glob("*.py") if not p.stem.startswith("_") and p.stem != "base")
        registered = sorted({m.__name__.rsplit(".", 1)[1] for m in io.FORMATS.values()})
        self.assertEqual(registered, modules)

    def test_existing_formats_keep_their_metadata(self):
        expected = {".txt": "text", ".md": "markdown", ".markdown": "markdown", ".srt": "srt", ".vtt": "vtt"}
        self.assertEqual({e: n for e, n in io.EXTENSIONS.items() if e in expected}, expected)
        self.assertEqual(io.REGISTRY.fallback, "text")
        self.assertEqual(io.REGISTRY.sniff_order[:3], ["vtt", "srt", "markdown"])

    def test_routes_and_harness_derive_from_the_registry(self):
        self.assertEqual(routes.FILE_EXTENSIONS, {n: e for n, e in io.OUTPUTS.items() if n != "text"})
        self.assertEqual(set(harness.FORMATS), set(io.FORMATS))

    def test_a_new_module_is_picked_up_without_editing_core(self):
        registry = io.Registry(io.discover() + [fake_module()])
        self.assertIn("fake", registry.names())
        self.assertEqual(registry.detect("anything", "notes.FAKE"), "fake")
        self.assertEqual(registry.detect("FAKE header\nline"), "fake")  # priority 99 sniffs first
        self.assertEqual(registry.detect("plain words"), "text")
        self.assertEqual(registry.outputs()["fake"], ".fake")

    def test_options_reach_extract_and_rebuild(self):
        registry = io.Registry(io.discover() + [fake_module()])
        with mock.patch.object(io, "REGISTRY", registry):
            segs = io.extract("a\nb", "fake", ["upper=true"])
            self.assertEqual([s["text"] for s in segs], ["A", "B"])
            self.assertEqual(io.rebuild("a\nb", "fake", {2: "c"}, {"upper": False}), "a\nc")

    def test_option_parsing(self):
        registry = io.Registry(io.discover() + [fake_module(options={
            "cols": {"type": "list"}, "n": {"type": "int"}, "on": {"type": "bool"}, "s": {"type": "str"}})])
        parsed = registry.options("fake", ["cols=a, b", "n=3", "on=false", "s=x=y"])
        self.assertEqual(parsed, {"cols": ["a", "b"], "n": 3, "on": False, "s": "x=y"})
        for bad in (["n=three"], ["on=maybe"], ["nokey"], ["=v"], ["other=1"]):
            with self.assertRaises(io.FormatError, msg=bad):
                registry.options("fake", bad)
        with self.assertRaises(io.FormatError):
            registry.options("fake", {"n": [3]})  # typed values must match the declared type
        self.assertEqual(registry.options("fake", {"n": 3, "cols": ["a"]}), {"n": 3, "cols": ["a"]})

    def test_existing_formats_have_no_options(self):
        for name in io.FORMATS:
            with self.assertRaises(io.FormatError):
                io.options(name, ["x=1"])

    def test_malformed_specs_are_rejected(self):
        base = io.discover()
        bad = [
            [fake_module(extensions=[".md"])],                   # extension already claimed
            [fake_module(name="text")],                          # name already registered
            [fake_module(fallback=True)],                        # second fallback
            [fake_module(output="fake")],                        # output without a dot
            [fake_module(options={"x": {"type": "float"}})],     # unknown option type
            [fake_module(color="red")],                          # unknown spec key
        ]
        for extra in bad:
            with self.assertRaises(io.FormatError, msg=extra[0].SPECS):
                io.Registry(base + extra)
        with self.assertRaises(io.FormatError):
            io.Registry([fake_module()])  # no fallback format


class ContractTest(unittest.TestCase):
    """Every registered format passes the same round-trip contract on its sample file."""

    def sample(self, name):
        """The sample source of format ``name`` (one file per format in tests/format_samples)."""
        path = SAMPLES / f"{name}{io.OUTPUTS[name]}"
        self.assertTrue(path.is_file(), f"add a sample for format {name}: {path.name}")
        return path.read_text(encoding="utf-8")

    def sources(self, name):
        """The LF sample and its CRLF variant."""
        lf = self.sample(name)
        return [lf, lf.replace("\n", "\r\n")]

    def test_every_format_has_a_sample(self):
        for name in io.FORMATS:
            self.sample(name)

    def test_unchanged_round_trip_is_byte_equal(self):
        for name in io.FORMATS:
            for source in self.sources(name):
                segs = io.extract(source, name)
                self.assertTrue(segs, name)
                self.assertEqual(io.rebuild(source, name, {}), source, name)
                self.assertEqual(io.rebuild(source, name, {s["id"]: s["text"] for s in segs}), source, name)

    def test_segment_spans_are_ordered_and_inside_the_source(self):
        for name in io.FORMATS:
            for source in self.sources(name):
                pos = 0
                for seg in io.extract(source, name):
                    self.assertLessEqual(pos, seg["start"], name)
                    self.assertLessEqual(seg["start"], seg["end"], name)
                    self.assertLessEqual(seg["end"], len(source), name)
                    pos = seg["end"]

    def test_rewriting_every_segment_keeps_the_skeleton(self):
        for name in io.FORMATS:
            for source in self.sources(name):
                before = io.extract(source, name)
                rewritten = {s["id"]: f"Rewritten segment {s['id']}." for s in before}
                output = io.rebuild(source, name, rewritten)
                after = io.extract(output, name)
                self.assertEqual([s["text"] for s in after], list(rewritten.values()), name)
                self.assertEqual(skeleton(output, after), skeleton(source, before), name)

    def test_crlf_stays_crlf(self):
        for name in io.FORMATS:
            source = self.sources(name)[1]
            segs = io.extract(source, name)
            output = io.rebuild(source, name, {segs[0]["id"]: "One line\nand another"})
            self.assertNotIn("\n", output.replace("\r\n", ""), name)


class CliTest(unittest.TestCase):
    """``--format-option`` is validated by the format and reaches ``pe run init``."""

    def pe(self, *args):
        """Run ``pe`` and return the exit code and parsed JSON."""
        proc = subprocess.run([sys.executable, str(PE), *args], capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout)

    def test_unknown_option_is_a_usage_error(self):
        code, out = self.pe("extract", "--text", "# Title", "--format", "markdown", "--format-option", "x=1")
        self.assertEqual(code, 2)
        self.assertIn("has no option 'x'", out["error"])

    def test_run_init_validates_options(self):
        code, out = self.pe("run", "init", str(SAMPLES / "markdown.md"), "--format-option", "x=1")
        self.assertEqual(code, 2)
        self.assertIn("has no option", out["error"])


class DocsTest(unittest.TestCase):
    """references/formats.md lists exactly the registered formats and their extensions."""

    def test_formats_table_matches_the_registry(self):
        rows = {}
        for line in FORMATS_MD.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0].startswith("`") and cells[1].startswith("`."):
                rows[cells[0].strip("`")] = sorted(e.strip(" `") for e in cells[1].split(","))
        expected = {name: sorted(e for e, n in io.EXTENSIONS.items() if n == name) for name in io.FORMATS}
        self.assertEqual(rows, expected)


if __name__ == "__main__":
    unittest.main()
