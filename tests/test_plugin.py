"""Tests for plugin packaging, manifest validity, and zero-install execution (story 010).

Verifies that .claude-plugin/plugin.json and marketplace.json are valid, refer to existing files,
keep versions in sync with core package, and run zero-install end-to-end without pip.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

import _path  # noqa: F401
import paraphrase_everything

ROOT = Path(__file__).parent.parent
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
PE = ROOT / "skills" / "paraphrase-anything" / "scripts" / "pe.py"


class PluginManifestTest(unittest.TestCase):
    """Verify plugin and marketplace manifests for Claude Code."""

    def test_plugin_json_valid_and_consistent(self):
        self.assertTrue(PLUGIN_JSON.exists(), "missing .claude-plugin/plugin.json")
        data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        for field in ("name", "version", "description", "author", "license", "skills"):
            self.assertIn(field, data)
        self.assertEqual(data["version"], paraphrase_everything.__version__)
        for skill_path in data.get("skills", []):
            resolved = (ROOT / skill_path).resolve()
            self.assertTrue(resolved.exists(), f"skill path {skill_path} does not exist")
            self.assertTrue((resolved / "SKILL.md").exists(), f"missing SKILL.md in {skill_path}")
        for cmd_path in data.get("commands", []):
            resolved = (ROOT / cmd_path).resolve()
            self.assertTrue(resolved.exists(), f"command path {cmd_path} does not exist")

    def test_marketplace_json_valid_and_consistent(self):
        self.assertTrue(MARKETPLACE_JSON.exists(), "missing .claude-plugin/marketplace.json")
        data = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
        for field in ("name", "description", "owner", "plugins"):
            self.assertIn(field, data)
        self.assertGreater(len(data["plugins"]), 0)
        plugin = next((p for p in data["plugins"] if p["name"] == "paraphrase-anything"), None)
        self.assertIsNotNone(plugin, "missing paraphrase-anything in marketplace.json")
        self.assertEqual(plugin["version"], paraphrase_everything.__version__)

    def test_version_sync_with_packaging_if_present(self):
        pyproject = ROOT / "pyproject.toml"
        if pyproject.exists():
            import re
            m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', pyproject.read_text(encoding="utf-8"))
            if m:
                self.assertEqual(m.group(1), paraphrase_everything.__version__,
                                 "pyproject.toml version does not match package __version__")


class ZeroInstallExecutionTest(unittest.TestCase):
    """Verify end-to-end execution without pip install (stdlib only)."""

    def run_cmd(self, *args, stdin=None):
        cmd = [sys.executable, str(PE), *args]
        proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8")
        out = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else proc.stdout
        return proc.returncode, out

    def test_end_to_end_raw_text_pipeline(self):
        orig = "The project launched in 2024 with 10 core principles."
        masked_code, masked_res = self.run_cmd("protect", "--text", orig)
        self.assertEqual(masked_code, 0)
        self.assertTrue(masked_res["ok"])

        rewrite = "In 2024, the initiative debuted around 10 foundational principles."
        check_code, check_res = self.run_cmd("check", "--original-text", orig, "--rewritten-text", rewrite)
        self.assertEqual(check_code, 0)
        self.assertTrue(check_res["ok"])

        metrics_code, metrics_res = self.run_cmd("metrics", "--original-text", orig,
                                                 "--rewritten-text", rewrite, "--mode", "standard")
        self.assertEqual(metrics_code, 0)
        self.assertTrue(metrics_res["ok"])

        pair_code, pair_res = self.run_cmd("metrics", "--pairwise", "--variant", orig, "--variant", rewrite)
        self.assertEqual(pair_code, 0)
        self.assertTrue(pair_res["ok"])


if __name__ == "__main__":
    unittest.main()
