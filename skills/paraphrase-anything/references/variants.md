# Variant Diversity Guide

When generating multiple variants of a text, each version must differ in substance rather than just swapping a few synonyms. Use distinct **axes of variation** while keeping facts, numbers, and core meaning strictly intact.

## Diversity axes

| Axis | Description | Typical techniques |
|------|-------------|-------------------|
| **Structure** | Reorganise clause and sentence order | Invert condition and outcome; merge two short sentences; split a compound sentence. |
| **Register** | Shift tone and audience alignment | Formal / academic vs approachable / conversational; professional vs journalistic. |
| **Concision** | Adjust information density | Tighten to essentials (lean) vs elaborate context smoothly (expressive). |
| **Voice** | Change grammatical perspective | Shift between active and passive constructions; front key topics (topicalisation). |
| **Vocabulary** | Alternate conceptual phrasing | Rephrase core ideas using distinct lexical fields without jargon or clichés. |

## Selecting axes by mode

- **standard:** Combine *Structure* and *Vocabulary* while preserving standard register.
- **light:** Subtle *Vocabulary* and mild *Voice* shifts; keep structure close to original.
- **creative:** Bold *Structure* reorganisation paired with *Register* or *Voice* shifts.
- **shorten:** Combine *Concision* with *Structure* (compress clauses into concise phrases).
- **expand:** Pair *Vocabulary* and *Structure* to spell out implications and context.

## Workflow

1. **Assign distinct axes:** For N variants, choose N different primary axes.
2. **Verify fidelity individually:**
   ```bash
   pe check original.txt v1.txt
   pe check original.txt v2.txt
   ```
   Or for raw text:
   ```bash
   pe check --original-text "..." --rewritten-text "..."
   ```
3. **Verify divergence across variants:**
   ```bash
   pe metrics --pairwise v1.txt v2.txt v3.txt
   ```
   Or for inline raw text:
   ```bash
   pe metrics --pairwise --variant "variant 1" --variant "variant 2" --variant "variant 3"
   ```
4. **Resolve duplicates:** If any pair is flagged in `too_similar` (overlap > threshold, default `0.50`), rewrite the weaker variant along an unused axis (at most 1 extra round).

## Response format

Present variants clearly labelled with their primary axis and a brief rationale:

```markdown
### Variant 1 — Structure (clause inversion)
> [Variant text]

### Variant 2 — Register (formal / academic)
> [Variant text]

### Variant 3 — Concision (direct and punchy)
> [Variant text]

*Checked: all variants verified for factual fidelity and pairwise diversity.*
```
