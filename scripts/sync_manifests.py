"""Synchronize and verify metadata across all tool distribution manifests (story 014).

Maintains single source of truth (.claude-plugin/plugin.json) and ensures no version
or description drift occurs across tool adapters in integrations/.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"


def get_canonical_metadata(root=None):
    """Read the canonical name, version, and description from .claude-plugin/plugin.json."""
    root_path = Path(root) if root else ROOT
    canonical_file = root_path / ".claude-plugin" / "plugin.json"
    if not canonical_file.exists():
        raise FileNotFoundError(f"Canonical manifest not found: {canonical_file}")
    data = json.loads(canonical_file.read_text(encoding="utf-8"))
    return {
        "name": data["name"],
        "version": data["version"],
        "description": data["description"],
    }


def find_all_manifests(root=None):
    """Find all JSON and TOML manifests across repository integrations."""
    root_path = Path(root) if root else ROOT
    manifests = []

    # Claude plugin & marketplace
    claude_plugin = root_path / ".claude-plugin" / "plugin.json"
    if claude_plugin.exists():
        manifests.append(claude_plugin)
    marketplace = root_path / ".claude-plugin" / "marketplace.json"
    if marketplace.exists():
        manifests.append(marketplace)

    # Tool integrations in integrations/
    integrations_dir = root_path / "integrations"
    if integrations_dir.exists():
        for ext in ("*.json", "*.toml"):
            manifests.extend(integrations_dir.rglob(ext))

    # Packaging pyproject.toml if present
    pyproject = root_path / "pyproject.toml"
    if pyproject.exists():
        manifests.append(pyproject)

    return sorted(set(manifests))


def check_manifest_drift(root=None):
    """Compare all manifests against canonical metadata; return list of drift records."""
    root_path = Path(root) if root else ROOT
    canonical = get_canonical_metadata(root_path)
    drifts = []

    for manifest_path in find_all_manifests(root_path):
        rel_path = manifest_path.relative_to(root_path).as_posix()
        text = manifest_path.read_text(encoding="utf-8")

        if manifest_path.name == "marketplace.json":
            data = json.loads(text)
            for plugin in data.get("plugins", []):
                if plugin.get("name") == canonical["name"]:
                    if plugin.get("version") != canonical["version"]:
                        drifts.append({
                            "path": rel_path,
                            "field": "version",
                            "expected": canonical["version"],
                            "actual": plugin.get("version"),
                        })
                    if plugin.get("description") != canonical["description"]:
                        drifts.append({
                            "path": rel_path,
                            "field": "description",
                            "expected": canonical["description"],
                            "actual": plugin.get("description"),
                        })
        elif manifest_path.suffix == ".json":
            data = json.loads(text)
            if "version" in data and data["version"] != canonical["version"]:
                drifts.append({
                    "path": rel_path,
                    "field": "version",
                    "expected": canonical["version"],
                    "actual": data["version"],
                })
            if "description" in data and data["description"] != canonical["description"]:
                drifts.append({
                    "path": rel_path,
                    "field": "description",
                    "expected": canonical["description"],
                    "actual": data["description"],
                })
        elif manifest_path.suffix == ".toml":
            m_ver = re.search(r'version\s*=\s*["\']([^"\']+)["\']', text)
            if m_ver and m_ver.group(1) != canonical["version"]:
                drifts.append({
                    "path": rel_path,
                    "field": "version",
                    "expected": canonical["version"],
                    "actual": m_ver.group(1),
                })
            m_desc = re.search(r'description\s*=\s*["\']([^"\']+)["\']', text)
            if m_desc and m_desc.group(1) != canonical["description"]:
                drifts.append({
                    "path": rel_path,
                    "field": "description",
                    "expected": canonical["description"],
                    "actual": m_desc.group(1),
                })

    return drifts


def sync_all_manifests(root=None):
    """Propagate canonical version and description to all tool manifests."""
    root_path = Path(root) if root else ROOT
    canonical = get_canonical_metadata(root_path)
    updated = []

    for manifest_path in find_all_manifests(root_path):
        if manifest_path == CANONICAL_MANIFEST:
            continue
        rel_path = manifest_path.relative_to(root_path).as_posix()
        text = manifest_path.read_text(encoding="utf-8")

        if manifest_path.name == "marketplace.json":
            data = json.loads(text)
            changed = False
            for plugin in data.get("plugins", []):
                if plugin.get("name") == canonical["name"]:
                    if plugin.get("version") != canonical["version"]:
                        plugin["version"] = canonical["version"]
                        changed = True
                    if plugin.get("description") != canonical["description"]:
                        plugin["description"] = canonical["description"]
                        changed = True
            if changed:
                manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                updated.append(rel_path)
        elif manifest_path.suffix == ".json":
            data = json.loads(text)
            changed = False
            if "version" in data and data["version"] != canonical["version"]:
                data["version"] = canonical["version"]
                changed = True
            if "description" in data and data["description"] != canonical["description"]:
                data["description"] = canonical["description"]
                changed = True
            if changed:
                manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                updated.append(rel_path)
        elif manifest_path.suffix == ".toml":
            new_text = re.sub(r'(version\s*=\s*["\'])[^"\']+(["\'])', rf'\g<1>{canonical["version"]}\g<2>', text)
            new_text = re.sub(r'(description\s*=\s*["\'])[^"\']+(["\'])', rf'\g<1>{canonical["description"]}\g<2>', new_text)
            if new_text != text:
                manifest_path.write_text(new_text, encoding="utf-8")
                updated.append(rel_path)

    return updated


def main(argv=None):
    """CLI entry point for checking or syncing manifest metadata."""
    parser = argparse.ArgumentParser(description="Synchronize and verify tool manifests metadata")
    parser.add_argument("--check", action="store_true", default=True, help="Check for metadata drift (default)")
    parser.add_argument("--write", action="store_true", help="Write canonical metadata to all manifests")
    args = parser.parse_args(argv)

    if args.write:
        updated = sync_all_manifests()
        if updated:
            print(f"Updated {len(updated)} manifest(s):")
            for p in updated:
                print(f"  - {p}")
        else:
            print("All manifests are already in sync with canonical metadata.")
        return 0

    drifts = check_manifest_drift()
    if drifts:
        print(f"FAILED: Found {len(drifts)} metadata drift(s):", file=sys.stderr)
        for d in drifts:
            print(f"  - {d['path']} [{d['field']}]: expected '{d['expected']}', got '{d['actual']}'", file=sys.stderr)
        return 1

    print("OK: All manifests share canonical name, version, and description.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
