# Tool Integration Notes

Notes on running the `paraphrase-anything` skill across supported AI agent harnesses.

## OpenAI Codex CLI

- **Manifest:** `integrations/codex/codex.json` defines skill and prompt entry points.
- **Global Install:** Copy or symlink `skills/paraphrase-anything` to `~/.codex/skills/paraphrase-anything`.
- **Prompts:** Copy `integrations/codex/prompts/paraphrase.md` to `~/.codex/prompts/paraphrase.md` to enable `/paraphrase`.
- **Project Configuration:** In repositories where Codex operates, include a reference to `skills/paraphrase-anything/SKILL.md` in `AGENTS.md`.

## Claude Code

- **Manifest:** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
- **Install:** `/plugin marketplace add ngwgsang/paraphrase-everything` and `/plugin install paraphrase-anything`.
- **Command:** Registered automatically via `commands/paraphrase.md`.

## Execution Model

All tools execute the same zero-install tooling:
```bash
python skills/paraphrase-anything/scripts/pe.py check original.txt rewrite.txt
python skills/paraphrase-anything/scripts/pe.py metrics original.txt rewrite.txt --mode standard
```
No `pip install` or external dependencies required.
