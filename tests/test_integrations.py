"""Tests for multi-tool distribution foundation (story 014).

Verifies that all tool manifests in the repository share canonical metadata without drift,
and checks that the integrations convention is properly maintained.
"""

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


if __name__ == "__main__":
    unittest.main()
