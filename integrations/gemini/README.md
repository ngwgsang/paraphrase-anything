# Gemini CLI Extension

Gemini CLI installs extensions from the repository root, so the manifest lives there rather than
in this folder:

| File | Purpose |
|------|---------|
| `gemini-extension.json` | Extension manifest (name, version, description, `contextFileName`) |
| `GEMINI.md` | Context file; imports `skills/paraphrase-anything/SKILL.md` |
| `commands/paraphrase.toml` | `/paraphrase` command, mirroring `commands/paraphrase.md` |

No skill content is duplicated: `GEMINI.md` and the command point at the canonical skill.

## Installation

```bash
gemini extensions install https://github.com/ngwgsang/paraphrase-anything
```

For local development, link a checkout instead:

```bash
gemini extensions link /path/to/paraphrase-anything
```

## Quickstart

```text
/paraphrase creative Our Q3 revenue grew 12% to $4.2M.
/paraphrase light notes.md
```

Or ask naturally: "paraphrase this paragraph in a formal tone".

## Zero-Install Execution
No `pip install` is required. All bundled tooling uses only the **Python ≥ 3.10 standard library**.
