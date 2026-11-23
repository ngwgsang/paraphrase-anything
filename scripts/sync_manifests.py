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

    # Gemini CLI requires its manifest at the repository root
    gemini = root_path / "gemini-extension.json"
    if gemini.exists():
        manifests.append(gemini)

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


FIELDS = ("version", "description")


def _toml_pattern(field):
    """Regex matching a top-level `field = "value"` line, with the value as group 2."""
    return re.compile(
        rf"^(\s*{field}\s*=\s*)(\"(?:[^\"\\]|\\.)*\"|'[^']*')", re.MULTILINE)


def _toml_value(raw):
    """Decode a quoted TOML string literal matched by `_toml_pattern`."""
    return json.loads(raw) if raw.startswith('"') else raw[1:-1]


def _toml_literal(value):
    """Encode a string as a TOML basic string (JSON escaping is compatible)."""
    return json.dumps(value, ensure_ascii=False)


def _read_fields(path, canonical):
    """Return {field: value} for version/description declared in a manifest."""
    text = path.read_text(encoding="utf-8")
    if path.name == "marketplace.json":
        for plugin in json.loads(text).get("plugins", []):
            if plugin.get("name") == canonical["name"]:
                return {f: plugin[f] for f in FIELDS if f in plugin}
        return {}
    if path.suffix == ".json":
        data = json.loads(text)
        return {f: data[f] for f in FIELDS if f in data}
    found = {}
    for field in FIELDS:
        match = _toml_pattern(field).search(text)
        if match:
            found[field] = _toml_value(match.group(2))
    return found


def check_manifest_drift(root=None):
    """Compare all manifests against canonical metadata; return list of drift records."""
    root_path = Path(root) if root else ROOT
    canonical = get_canonical_metadata(root_path)
    drifts = []
    for manifest_path in find_all_manifests(root_path):
        rel_path = manifest_path.relative_to(root_path).as_posix()
        for field, actual in _read_fields(manifest_path, canonical).items():
            if actual != canonical[field]:
                drifts.append({
                    "path": rel_path,
                    "field": field,
                    "expected": canonical[field],
                    "actual": actual,
                })
    return drifts


def _write_json(path, data):
    """Write JSON as UTF-8 with a trailing newline, without newline translation."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="")


def sync_all_manifests(root=None):
    """Propagate canonical version and description to all tool manifests."""
    root_path = Path(root) if root else ROOT
    canonical = get_canonical_metadata(root_path)
    canonical_file = root_path / ".claude-plugin" / "plugin.json"
    updated = []
    for manifest_path in find_all_manifests(root_path):
        if manifest_path == canonical_file:
            continue
        text = manifest_path.read_text(encoding="utf-8")
        if manifest_path.suffix == ".json":
            data = json.loads(text)
            if manifest_path.name == "marketplace.json":
                targets = [p for p in data.get("plugins", []) if p.get("name") == canonical["name"]]
            else:
                targets = [data]
            changed = False
            for target in targets:
                for field in FIELDS:
                    if field in target and target[field] != canonical[field]:
                        target[field] = canonical[field]
                        changed = True
            if changed:
                _write_json(manifest_path, data)
                updated.append(manifest_path.relative_to(root_path).as_posix())
        else:
            new_text = text
            for field in FIELDS:
                literal = _toml_literal(canonical[field])
                new_text = _toml_pattern(field).sub(
                    lambda m, lit=literal: m.group(1) + lit, new_text, count=1)
            if new_text != text:
                manifest_path.write_text(new_text, encoding="utf-8", newline="")
                updated.append(manifest_path.relative_to(root_path).as_posix())
    return updated


def main(argv=None):
    """CLI entry point for checking or syncing manifest metadata."""
    parser = argparse.ArgumentParser(description="Synchronize and verify tool manifests metadata")
    parser.add_argument("--check", action="store_true",
                        help="Check for metadata drift (the default; conflicts with --write)")
    parser.add_argument("--write", action="store_true",
                        help="Write canonical metadata to all manifests (default: only check for drift)")
    args = parser.parse_args(argv)
    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")

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
