# OpenAI Codex CLI Integration

This adapter enables automatic discovery and execution of the `paraphrase-anything` skill within the OpenAI Codex CLI.

## Installation

### Option 1: Via Skills CLI (Recommended)
```bash
npx skills add ngwgsang/paraphrase-anything
```

### Option 2: Copy or Symlink into Codex Skills
Link or copy the canonical skill directory into your user Codex skills directory:

**macOS / Linux:**
```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/skills/paraphrase-anything" ~/.codex/skills/paraphrase-anything
```

**Windows (PowerShell):**
```powershell
New-Item -ItemType Directory -Force -Path "$HOME\.codex\skills"
Copy-Item -Recurse -Path ".\skills\paraphrase-anything" -Destination "$HOME\.codex\skills\paraphrase-anything"
```

### Slash Command Setup (`/paraphrase`)
To register the `/paraphrase` prompt command in Codex:

**macOS / Linux:**
```bash
mkdir -p ~/.codex/prompts
cp integrations/codex/prompts/paraphrase.md ~/.codex/prompts/paraphrase.md
```

**Windows (PowerShell):**
```powershell
New-Item -ItemType Directory -Force -Path "$HOME\.codex\prompts"
Copy-Item "integrations\codex\prompts\paraphrase.md" "$HOME\.codex\prompts\paraphrase.md"
```

## `AGENTS.md` Snippet (Project Fallback)
If you prefer project-level configuration without installing globally, add this snippet to your repository's `AGENTS.md`:

```markdown
## Paraphrase Skill
This repository uses the `paraphrase-anything` skill.
- Entry point: `skills/paraphrase-anything/SKILL.md`
- Tooling CLI: `python skills/paraphrase-anything/scripts/pe.py <command>`
- Workflow: pin original -> rewrite -> verify with `pe check` -> measure with `pe metrics`.
```

## Zero-Install Execution
No `pip install` is required. All bundled tooling requires only the **Python ≥ 3.10 standard library**.
