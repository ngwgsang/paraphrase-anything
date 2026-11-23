# Cursor Integration

A description-triggered rule (`alwaysApply: false`) that makes Cursor's agent follow the
`paraphrase-anything` skill when you ask it to rewrite text. The rule is a short pointer; the
workflow lives in `SKILL.md`.

Windsurf uses the same body: see [../windsurf/](../windsurf/README.md).

## Installation

Run from your project root, with this repository checked out at `<repo>`.

**macOS / Linux:**
```bash
cp -r <repo>/skills/paraphrase-anything .paraphrase-anything
mkdir -p .cursor/rules
cp <repo>/integrations/cursor/rules/paraphrase.mdc .cursor/rules/paraphrase.mdc
```

**Windows (PowerShell):**
```powershell
Copy-Item -Recurse "<repo>\skills\paraphrase-anything" ".paraphrase-anything"
New-Item -ItemType Directory -Force ".cursor\rules"
Copy-Item "<repo>\integrations\cursor\rules\paraphrase.mdc" ".cursor\rules\paraphrase.mdc"
```

The rule expects the skill at `.paraphrase-anything/` in the project root. Commit it, or add it
to `.gitignore` if you prefer.

## Usage

Ask in Agent chat: "paraphrase this paragraph in a formal tone", "viết lại đoạn này", or
"言い換えて". Cursor decides from the rule description when to load it; you can also attach it
with `@paraphrase`.

## Zero-Install Execution
No `pip install` is required. All bundled tooling uses only the **Python ≥ 3.9 standard library**.
