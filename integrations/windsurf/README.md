# Windsurf Integration

A model-decision rule (`trigger: model_decision`): Cascade reads the description and loads the
rule when you ask it to rewrite text. The rule is a short pointer; the workflow lives in
`SKILL.md`.

Cursor uses the same body: see [../cursor/](../cursor/README.md).

## Installation

Run from your project root, with this repository checked out at `<repo>`.

**macOS / Linux:**
```bash
cp -r <repo>/skills/paraphrase-anything .paraphrase-anything
mkdir -p .windsurf/rules
cp <repo>/integrations/windsurf/rules/paraphrase.md .windsurf/rules/paraphrase.md
```

**Windows (PowerShell):**
```powershell
Copy-Item -Recurse "<repo>\skills\paraphrase-anything" ".paraphrase-anything"
New-Item -ItemType Directory -Force ".windsurf\rules"
Copy-Item "<repo>\integrations\windsurf\rules\paraphrase.md" ".windsurf\rules\paraphrase.md"
```

The rule expects the skill at `.paraphrase-anything/` in the project root.

## Usage

Ask Cascade: "paraphrase this paragraph in a formal tone", "viết lại đoạn này", or "言い換えて".

## Zero-Install Execution
No `pip install` is required. All bundled tooling uses only the **Python ≥ 3.9 standard library**.
