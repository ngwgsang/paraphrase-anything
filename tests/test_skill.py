import json
import re
import unittest
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import lang
from paraphrase_everything.cli import build_parser

SKILL_DIR = Path(_path.SCRIPTS).parent
SKILL_MD = SKILL_DIR / "SKILL.md"


def frontmatter(text):
    """Parse the simple ``key: value`` YAML frontmatter of SKILL.md."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with a frontmatter block"
    return dict(line.split(": ", 1) for line in match.group(1).splitlines())


def subcommand_flags():
    """Map each pe subcommand to the set of option strings it accepts."""
    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    return {name: {s for a in p._actions for s in a.option_strings}
            for name, p in sub.choices.items()}


class SkillMdTest(unittest.TestCase):
    def setUp(self):
        self.text = SKILL_MD.read_text(encoding="utf-8")

    def test_frontmatter(self):
        meta = frontmatter(self.text)
        self.assertEqual(meta["name"], "paraphrase-anything")
        self.assertLessEqual(len(meta["description"]), 1024)
        for trigger in ("paraphrase", "rewrite", "viết lại", "言い換え"):
            self.assertIn(trigger, meta["description"])

    def test_length_budget(self):
        self.assertLessEqual(len(self.text.splitlines()), 200)

    def test_relative_links_exist(self):
        for target in re.findall(r"\]\(([^)#]+)\)", self.text):
            if "://" not in target:
                self.assertTrue((SKILL_DIR / target).exists(), target)

    def test_every_language_has_a_note(self):
        for code in lang.available():
            self.assertTrue((SKILL_DIR / "references" / "languages" / f"{code}.md").exists(), code)

    def test_pe_commands_and_flags_exist(self):
        """Every `pe <command> --flag` written in the docs must exist in the CLI."""
        flags = subcommand_flags()
        docs = [SKILL_MD] + sorted((SKILL_DIR / "references").rglob("*.md"))
        for doc in docs:
            for line in doc.read_text(encoding="utf-8").splitlines():
                for m in re.finditer(r"\bpe (\w+)([^`\n]*)", line):
                    command, rest = m.groups()
                    if command not in flags:
                        continue  # prose such as "pe is zero-install"
                    for flag in re.findall(r"(?<![\w-])(--?[a-z][\w-]*)", rest):
                        self.assertIn(flag, flags[command], f"{doc.name}: pe {command} {flag}")
        self.assertIn("check", flags)


class ResponseDocTest(unittest.TestCase):
    """Verify the response format (change table and follow-ups) is documented and linked."""

    def setUp(self):
        self.skill = SKILL_MD.read_text(encoding="utf-8")
        self.doc = (SKILL_DIR / "references" / "response.md").read_text(encoding="utf-8")

    def test_skill_requires_table_and_follow_ups(self):
        self.assertIn("references/response.md", self.skill)
        self.assertIn("What changed", self.skill)
        self.assertIn("follow-up", self.skill)

    def test_doc_defines_table_and_follow_ups(self):
        self.assertIn("| Original | Rewritten | Change |", self.doc)
        self.assertIn("## Follow-ups", self.doc)
        self.assertIn("Quote verbatim", self.doc)

    def test_every_language_has_header_labels(self):
        for code in lang.available():
            self.assertRegex(self.doc, rf"(?m)^\| {code} \|", f"no header labels for {code}")


class ModesDocTest(unittest.TestCase):
    def test_bands_match_modes_json(self):
        modes = json.loads((Path(_path.SCRIPTS) / "paraphrase_everything" / "modes.json")
                           .read_text(encoding="utf-8"))
        doc = (SKILL_DIR / "references" / "modes.md").read_text(encoding="utf-8")
        for name, bands in modes.items():
            row = re.search(rf"^\| `{name}` \|([^|]*)\|([^|]*)\|", doc, re.MULTILINE)
            self.assertIsNotNone(row, name)
            for band, cell in zip((bands["overlap"], bands["length_ratio"]), row.groups()):
                if band is not None:
                    self.assertIn(f"{band[0]:.2f}–{band[1]:.2f}", cell, f"{name}: {cell}")


if __name__ == "__main__":
    unittest.main()
