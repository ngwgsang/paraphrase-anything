# Integrations Directory

This directory contains thin adapters for various AI coding tools and agent harnesses.

## Architecture & Single Source of Truth

The skill content in `skills/paraphrase-anything/` is the **single source of truth** for:
- Prompt instructions, modes, and workflow ([SKILL.md](../skills/paraphrase-anything/SKILL.md))
- Advisory bands, language markers, and preservation rules ([references/](../skills/paraphrase-anything/references/))
- Deterministic verification and metrics tooling ([scripts/](../skills/paraphrase-anything/scripts/))

## Adapter Convention

Adapters in this directory must follow these rules:

1. **No Forked Skill Content**: Adapters must point to, symlink, or reference `skills/paraphrase-anything/`. Never duplicate prompt instructions or copy core Python logic into an adapter folder.
2. **Standard Manifests**: Each integration directory provides the manifest or configuration format required by the target tool (e.g. `codex.json`, `gemini-extension.json`, `.cursorrules`).
3. **Synchronized Metadata**: Tool manifests must share the same `name`, `version`, and `description` as `.claude-plugin/plugin.json`. Use `python scripts/sync_manifests.py` to verify or propagate metadata.
4. **Zero Install**: Adapters must execute `pe.py` using standard Python ≥ 3.10 without requiring `pip install`.

## Adding a New Tool

To add support for a new AI coding tool:
1. Create a folder `integrations/<tool_name>/`.
2. Add the tool-specific manifest or entry point pointing to the canonical skill.
3. Add a row to the **Installation** table in [README.md](../README.MD).
4. Run `python scripts/sync_manifests.py --check` and `python -m unittest discover -s tests`.
