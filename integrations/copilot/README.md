# GitHub Copilot (VS Code) Integration

A prompt file (`/paraphrase` in agent mode) and a scoped instructions file make Copilot follow
the `paraphrase-anything` skill and run its verification script. Both are short pointers; the
workflow lives in `SKILL.md`.

## Installation

Run from your project root, with this repository checked out at `<repo>`.

**macOS / Linux:**
```bash
cp -r <repo>/skills/paraphrase-anything .paraphrase-anything
mkdir -p .github/prompts .github/instructions
cp <repo>/integrations/copilot/prompts/paraphrase.prompt.md .github/prompts/
cp <repo>/integrations/copilot/instructions/paraphrase.instructions.md .github/instructions/
```

**Windows (PowerShell):**
```powershell
Copy-Item -Recurse "<repo>\skills\paraphrase-anything" ".paraphrase-anything"
New-Item -ItemType Directory -Force ".github\prompts", ".github\instructions"
Copy-Item "<repo>\integrations\copilot\prompts\paraphrase.prompt.md" ".github\prompts\"
Copy-Item "<repo>\integrations\copilot\instructions\paraphrase.instructions.md" ".github\instructions\"
```

The files expect the skill at `.paraphrase-anything/` in the project root.

## Usage

In Copilot Chat, switch to **Agent** mode and run:

```text
/paraphrase creative Our Q3 revenue grew 12% to $4.2M.
/paraphrase light notes.md
```

Or ask naturally ("paraphrase this paragraph in a formal tone"); the instructions file applies to
`.txt` and `.md` files in context.

## Agent Skills

Recent VS Code versions can load Agent Skills directly. If yours does, you can copy
`skills/paraphrase-anything` into the skills folder it documents instead of using the prompt and
instructions files above. Check your VS Code release notes; this adapter works without it.

## Zero-Install Execution
No `pip install` is required. All bundled tooling uses only the **Python ≥ 3.9 standard library**.
