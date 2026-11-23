"""Tests for the GitHub Copilot (VS Code) adapter (story 018)."""

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
COPILOT = ROOT / "integrations" / "copilot"
PROMPT = COPILOT / "prompts" / "paraphrase.prompt.md"
INSTRUCTIONS = COPILOT / "instructions" / "paraphrase.instructions.md"
SKILL_DIR_NAME = ".paraphrase-anything"


def parse(path):
    """Return ``(frontmatter dict, body)``; values stay raw strings."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match, f"{path.name}: missing frontmatter"
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, match.group(2)


class CopilotFrontmatterTest(unittest.TestCase):
    """Frontmatter keys match what VS Code reads for prompt and instructions files."""

    def test_prompt_runs_in_agent_mode_with_terminal(self):
        meta, _ = parse(PROMPT)
        self.assertEqual(set(meta), {"mode", "description", "tools"})
        self.assertEqual(meta["mode"], "agent")
        self.assertTrue(meta["description"])
        self.assertIn("runCommands", meta["tools"])
        self.assertIn("editFiles", meta["tools"])

    def test_instructions_scoped_to_text_files(self):
        meta, _ = parse(INSTRUCTIONS)
        self.assertEqual(set(meta), {"description", "applyTo"})
        patterns = meta["applyTo"].strip('"').split(",")
        self.assertEqual(sorted(patterns), ["**/*.md", "**/*.txt"])

    def test_file_names_follow_vscode_convention(self):
        self.assertTrue(PROMPT.name.endswith(".prompt.md"))
        self.assertTrue(INSTRUCTIONS.name.endswith(".instructions.md"))


class CopilotBodyTest(unittest.TestCase):
    """Files stay short pointers and run the verification script."""

    def test_prompt_runs_check_and_defers_to_skill(self):
        body = parse(PROMPT)[1]
        self.assertIn(f"{SKILL_DIR_NAME}/SKILL.md", body)
        self.assertIn(f"{SKILL_DIR_NAME}/scripts/pe.py", body)
        self.assertIn("pe check", body)
        self.assertIn("${input:request", body)
        self.assertNotIn("pe protect", body, "workflow steps must live in SKILL.md")
        for mode in ("standard", "light", "creative", "shorten", "expand"):
            self.assertIn(mode, body)

    def test_instructions_defer_to_skill_and_run_check(self):
        body = parse(INSTRUCTIONS)[1]
        self.assertIn(f"{SKILL_DIR_NAME}/SKILL.md", body)
        self.assertIn(f"{SKILL_DIR_NAME}/scripts/pe.py check", body)
        self.assertIn("ignore this file", body, "must not fire on unrelated requests")
        self.assertLessEqual(len(body.splitlines()), 25)

    def test_readme_and_root_row(self):
        readme = (COPILOT / "README.md").read_text(encoding="utf-8")
        for needle in (".github/prompts", ".github/instructions", SKILL_DIR_NAME, "Copy-Item", "Agent"):
            self.assertIn(needle, readme)
        self.assertIn("integrations/copilot/", (ROOT / "README.MD").read_text(encoding="utf-8"))


class CopilotInstalledPathsTest(unittest.TestCase):
    """Following the README install steps leaves every referenced path resolvable."""

    def test_paths_resolve_and_check_runs_after_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            shutil.copytree(SKILL, project / SKILL_DIR_NAME,
                            ignore=shutil.ignore_patterns("__pycache__"))
            for path in (PROMPT, INSTRUCTIONS):
                for rel in re.findall(rf"{re.escape(SKILL_DIR_NAME)}/[\w./-]+", parse(path)[1]):
                    if rel.endswith("pe.py check"):
                        continue
                    self.assertTrue((project / rel).exists(), f"{path.name}: {rel}")
            proc = subprocess.run(
                [sys.executable, str(project / SKILL_DIR_NAME / "scripts" / "pe.py"), "check",
                 "--original-text", "It costs 5 dollars.", "--rewritten-text", "The price is 5 dollars."],
                capture_output=True, text=True, encoding="utf-8", cwd=project)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
