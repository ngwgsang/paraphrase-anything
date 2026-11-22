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


class SyncManifestsWriteTest(unittest.TestCase):
    """Verify that --write propagation and TOML handling behave precisely."""

    def _make_repo(self, tmppath, toml=None):
        """Create a temp repo with a canonical manifest and an optional pyproject.toml."""
        plugin_dir = tmppath / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(
            '{"name": "paraphrase-anything", "version": "1.2.3", "description": "It\'s canonical"}',
            encoding="utf-8")
        (plugin_dir / "marketplace.json").write_text(
            '{"plugins": [{"name": "paraphrase-anything", "version": "0.0.1", "description": "old"},'
            ' {"name": "other", "version": "9.9.9"}]}', encoding="utf-8")
        integ = tmppath / "integrations" / "tool"
        integ.mkdir(parents=True)
        (integ / "manifest.json").write_text(
            '{"name": "x", "version": "0.0.2", "description": "old"}', encoding="utf-8")
        if toml is not None:
            (tmppath / "pyproject.toml").write_text(toml, encoding="utf-8")

    def test_write_syncs_json_and_leaves_other_plugins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._make_repo(tmppath)
            updated = sync_manifests.sync_all_manifests(tmppath)
            self.assertEqual(sorted(updated),
                             [".claude-plugin/marketplace.json", "integrations/tool/manifest.json"])
            self.assertEqual(sync_manifests.check_manifest_drift(tmppath), [])
            market = json.loads((tmppath / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
            self.assertEqual(market["plugins"][1]["version"], "9.9.9")

    def test_toml_only_top_level_keys_and_quotes(self):
        toml = ('[tool.x]\ntarget-version = "py39"\n\n[project]\nversion = "0.0.3"\n'
                'description = "old"\n')
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            self._make_repo(tmppath, toml)
            drifts = sync_manifests.check_manifest_drift(tmppath)
            toml_drifts = [d for d in drifts if d["path"] == "pyproject.toml"]
            self.assertEqual({d["field"] for d in toml_drifts}, {"version", "description"})
            sync_manifests.sync_all_manifests(tmppath)
            text = (tmppath / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn('target-version = "py39"', text)
            self.assertIn('version = "1.2.3"', text)
            self.assertIn("It's canonical", text)
            self.assertEqual(sync_manifests.check_manifest_drift(tmppath), [])


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

    def test_codex_prompt_defers_to_skill(self):
        prompt = (self.codex_dir / "prompts" / "paraphrase.md").read_text(encoding="utf-8")
        self.assertIn("SKILL.md", prompt)
        self.assertIn("scripts/pe.py", prompt)
        self.assertNotIn("\npe ", prompt, "bare `pe` is not an installed command")
        self.assertNotIn("```", prompt, "workflow steps must live in SKILL.md, not be copied")

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
