# Persona packs

One file per persona: `<name>.md`. No other file needs editing (SKILL.md points at this folder).

## Template

```markdown
---
name: <same as the file name>
description: <one line>
relax: []            # any of: length, overlap, lint
---

# <Name>

## Purpose
## Voice rules
## Do / Don't
## Language notes
## Examples

### en 1
**Input:** ...
**Output:** ...
```

## Rules
- At least 3 examples, covering at least 2 languages.
- Examples must pass `pe check`: numbers, citations, links, and code are kept exactly.
- `relax` may only list `length`, `overlap`, `lint`. Fidelity errors and negation/hedge
  warnings are never relaxed, and phrase allowlists are not allowed.
- Persona flourishes must never alter facts.
