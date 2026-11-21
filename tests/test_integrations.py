"""Tests for multi-tool distribution foundation (story 014).

Verifies that all tool manifests in the repository share canonical metadata without drift,
and checks that the integrations convention is properly maintained.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sync_manifests


class ManifestDriftTest(unittest.TestCase):
    """Verify that all distribution manifests match canonical metadata."""

    def test_canonical_manifest_exists(self):
        canonical = sync_manifests.get_canonical_metadata(ROOT)
        self.assertEqual(canonical["name"], "paraphrase-anything")
        self.assertTrue(canonical["version"])
        self.assertTrue(canonical["description"])

    def test_no_manifest_drift_in_repository(self):
        drifts = sync_manifests.check_manifest_drift(ROOT)
        self.assertEqual(drifts, [], f"Found manifest metadata drift: {drifts}")

    def test_drift_detected_when_manifest_diverges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            plugin_dir = tmppath / ".claude-plugin"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "plugin.json").write_text(
                '{"name": "paraphrase-anything", "version": "0.1.0", "description": "Canonical"}',
                encoding="utf-8"
            )
            integ_dir = tmppath / "integrations" / "testtool"
            integ_dir.mkdir(parents=True)
            (integ_dir / "manifest.json").write_text(
                '{"name": "paraphrase-anything", "version": "0.0.9", "description": "Outdated"}',
                encoding="utf-8"
            )
            drifts = sync_manifests.check_manifest_drift(tmppath)
            self.assertEqual(len(drifts), 2)
            fields = {d["field"] for d in drifts}
            self.assertEqual(fields, {"version", "description"})

    def test_sync_manifests_cli_check_passes(self):
        script = ROOT / "scripts" / "sync_manifests.py"
        proc = subprocess.run([sys.executable, str(script), "--check"], capture_output=True,
                              text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, f"sync_manifests.py failed:\n{proc.stderr}")
        self.assertIn("OK:", proc.stdout)


class IntegrationsConventionTest(unittest.TestCase):
    """Verify conventions for adding tool adapters."""

    def test_integrations_readme_exists_and_documents_convention(self):
        readme = ROOT / "integrations" / "README.md"
        self.assertTrue(readme.exists(), "missing integrations/README.md")
        content = readme.read_text(encoding="utf-8")
        self.assertIn("Single Source of Truth", content)
        self.assertIn("No Forked Skill Content", content)
        self.assertIn("Adding a New Tool", content)

    def test_readme_has_install_table(self):
        readme = ROOT / "README.MD"
        content = readme.read_text(encoding="utf-8")
        self.assertIn("## Installation", content)
        self.assertIn("| Tool / Environment |", content)
        self.assertIn("Claude Code", content)
        self.assertIn("Skills CLI", content)
        self.assertIn("OpenAI Codex CLI", content)


class CodexIntegrationTest(unittest.TestCase):
    """Verify OpenAI Codex CLI adapter packaging and zero-install execution (story 015)."""

    def setUp(self):
        self.codex_dir = ROOT / "integrations" / "codex"
        self.manifest_path = self.codex_dir / "codex.json"

    def test_codex_manifest_and_paths(self):
        self.assertTrue(self.manifest_path.exists(), "missing integrations/codex/codex.json")
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        canonical = sync_manifests.get_canonical_metadata(ROOT)
        self.assertEqual(data["name"], canonical["name"])
        self.assertEqual(data["version"], canonical["version"])
        self.assertEqual(data["description"], canonical["description"])
        for rel_skill in data.get("skills", []):
            skill_dir = (self.codex_dir / rel_skill).resolve()
            self.assertTrue(skill_dir.exists(), f"Skill directory not found: {skill_dir}")
            self.assertTrue((skill_dir / "SKILL.md").exists(), f"Missing SKILL.md in {skill_dir}")
        for rel_prompt in data.get("prompts", []):
            prompt_file = (self.codex_dir / rel_prompt).resolve()
            self.assertTrue(prompt_file.exists(), f"Prompt file not found: {prompt_file}")

    def test_codex_readme_and_agents_snippet(self):
        readme = self.codex_dir / "README.md"
        self.assertTrue(readme.exists(), "missing integrations/codex/README.md")
        content = readme.read_text(encoding="utf-8")
        self.assertIn("AGENTS.md", content)
        self.assertIn("~/.codex/skills", content)
        self.assertIn("~/.codex/prompts", content)
        self.assertIn("/paraphrase", content)

    def test_codex_zero_install_execution(self):
        pe_script = ROOT / "skills" / "paraphrase-anything" / "scripts" / "pe.py"
        proc = subprocess.run([
            sys.executable, str(pe_script), "check",
            "--original-text", "Codex launches with 5 parameters.",
            "--rewritten-text", "Codex initializes with 5 parameters."
        ], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"])


if __name__ == "__main__":
    unittest.main()
