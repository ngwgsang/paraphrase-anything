"""Tests for persona packs (story 009): structure, relax rules, and example fidelity."""

import re
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import check

SKILL_DIR = Path(_path.SCRIPTS).parent
PERSONAS = SKILL_DIR / "references" / "personas"
SECTIONS = ("Purpose", "Voice rules", "Do / Don't", "Language notes", "Examples")
RELAX_ALLOWED = {"length", "overlap", "lint"}
EXPECTED = {"formal", "casual", "academic", "simplify", "tsundere"}


def packs():
    """Return the persona pack files, excluding the folder README."""
    return sorted(p for p in PERSONAS.glob("*.md") if p.name != "README.md")


def parse(path):
    """Split a pack into its frontmatter dict, body text, and (lang, input, output) examples."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, f"{path.name}: missing frontmatter"
    meta = dict(line.split(": ", 1) for line in match.group(1).splitlines())
    body = match.group(2)
    examples = re.findall(
        r"### (\w+) \d+\n\*\*Input:\*\* (.+)\n\*\*Output:\*\* (.+)", body)
    return meta, body, examples


class PersonaPackTest(unittest.TestCase):
    """Every pack follows the template and keeps its examples faithful."""

    def test_initial_set_present(self):
        self.assertTrue(EXPECTED <= {p.stem for p in packs()})

    def test_frontmatter_and_sections(self):
        for path in packs():
            meta, body, _ = parse(path)
            self.assertEqual(meta["name"], path.stem)
            self.assertTrue(meta["description"].strip())
            for section in SECTIONS:
                self.assertIn(f"## {section}", body, f"{path.name}: {section}")

    def test_relax_only_soft_signals(self):
        for path in packs():
            meta, _, _ = parse(path)
            raw = meta["relax"].strip()
            self.assertTrue(raw.startswith("[") and raw.endswith("]"), path.name)
            values = {v.strip() for v in raw[1:-1].split(",") if v.strip()}
            self.assertLessEqual(values, RELAX_ALLOWED, path.name)

    def test_examples_count_and_languages(self):
        for path in packs():
            _, _, examples = parse(path)
            self.assertGreaterEqual(len(examples), 3, path.name)
            self.assertGreaterEqual(len({lang for lang, _, _ in examples}), 2, path.name)

    def test_examples_pass_fidelity_check(self):
        for path in packs():
            _, _, examples = parse(path)
            for code, original, rewritten in examples:
                report = check.check(original, rewritten, lang_code=code)
                self.assertEqual(report["errors"], [], f"{path.name} [{code}]: {original}")

    def test_skill_points_at_folder_without_listing_packs(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/personas/", skill)
        for name in EXPECTED:
            self.assertNotIn(f"personas/{name}.md", skill)


if __name__ == "__main__":
    unittest.main()
