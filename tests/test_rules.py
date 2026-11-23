"""Tests for the Cursor and Windsurf rule adapters (story 017)."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "paraphrase-anything"
CURSOR = ROOT / "integrations" / "cursor" / "rules" / "paraphrase.mdc"
WINDSURF = ROOT / "integrations" / "windsurf" / "rules" / "paraphrase.md"
SKILL_DIR_NAME = ".paraphrase-anything"


def parse(path):
    """Return ``(frontmatter dict, body)`` for a rule file; values stay raw strings."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, f"{path.name}: missing frontmatter"
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, match.group(2)


class RuleFrontmatterTest(unittest.TestCase):
    """Each tool's frontmatter has exactly the keys that tool understands."""

    def test_cursor_is_description_triggered(self):
        meta, _ = parse(CURSOR)
        self.assertEqual(set(meta), {"description", "globs", "alwaysApply"})
        self.assertEqual(meta["alwaysApply"], "false")
        self.assertEqual(meta["globs"], "")
        self.assertTrue(meta["description"])

    def test_windsurf_is_model_decision(self):
        meta, _ = parse(WINDSURF)
        self.assertEqual(set(meta), {"trigger", "description"})
        self.assertEqual(meta["trigger"], "model_decision")
        self.assertTrue(meta["description"])

    def test_descriptions_match_and_cover_trigger_phrases(self):
        cursor, windsurf = parse(CURSOR)[0], parse(WINDSURF)[0]
        self.assertEqual(cursor["description"], windsurf["description"])
        for phrase in ("paraphrase", "rewrite", "viết lại", "言い換え"):
            self.assertIn(phrase, cursor["description"])


class RuleBodyTest(unittest.TestCase):
    """Rules stay short pointers to the skill, not copies of it."""

    def test_bodies_identical_and_short(self):
        cursor, windsurf = parse(CURSOR)[1], parse(WINDSURF)[1]
        self.assertEqual(cursor, windsurf)
        self.assertLessEqual(len(cursor.splitlines()), 25)
        self.assertLessEqual(len(cursor), 12000)

    def test_body_defers_to_skill(self):
        body = parse(CURSOR)[1]
        self.assertIn(f"{SKILL_DIR_NAME}/SKILL.md", body)
        self.assertIn(f"{SKILL_DIR_NAME}/scripts/pe.py", body)
        self.assertNotIn("pe protect", body, "workflow steps must live in SKILL.md")

    def test_readmes_document_install(self):
        for tool, target in (("cursor", ".cursor/rules"), ("windsurf", ".windsurf/rules")):
            text = (ROOT / "integrations" / tool / "README.md").read_text(encoding="utf-8")
            self.assertIn(target, text)
            self.assertIn(SKILL_DIR_NAME, text)
            self.assertIn("Copy-Item", text)

    def test_root_readme_rows(self):
        text = (ROOT / "README.MD").read_text(encoding="utf-8")
        self.assertIn("integrations/cursor/", text)
        self.assertIn("integrations/windsurf/", text)


class InstalledPathsTest(unittest.TestCase):
    """Following the README install steps leaves every path in the rules resolvable."""

    def test_paths_resolve_after_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            shutil.copytree(SKILL, project / SKILL_DIR_NAME,
                            ignore=shutil.ignore_patterns("__pycache__"))
            for rule in (CURSOR, WINDSURF):
                body = parse(rule)[1]
                paths = re.findall(rf"{re.escape(SKILL_DIR_NAME)}/[\w./-]+", body)
                self.assertTrue(paths)
                for rel in paths:
                    self.assertTrue((project / rel).exists(), f"{rule.name}: {rel}")
            proc = subprocess.run(
                [sys.executable, str(project / SKILL_DIR_NAME / "scripts" / "pe.py"), "check",
                 "--original-text", "It costs 5 dollars.", "--rewritten-text", "The price is 5 dollars."],
                capture_output=True, text=True, encoding="utf-8", cwd=project)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
