# Layered rewriting (passes 3–5)

Each text pass changes one layer and is gated against the original before the next one runs.
Work from `inputs.previous`, apply only the `ops` your task lists, and write the whole text to
`output`. If the task lists `merged_passes`, you also own their ops.

| Pass | Owns | Must not |
|------|------|----------|
| **structure** (`p3-structure.txt`) | `split`, `merge`, `reorder` from the plan | reword beyond what the new structure needs |
| **lexis** (`p4-lexis.txt`) | `voice`, `clause`, `lexical` | add, remove, split, or merge sentences |
| **style** (`p5-style.txt`) | `register`, `shorten`, `expand`, the mode, persona, and length target | add claims that are not in the original |

## Rules for every pass

- **Placeholders.** Text passes start from `masked.txt`, where protected spans (code, URLs,
  LaTeX, kept terms) are replaced by `⟦P1⟧`, `⟦P2⟧`, ...; the task lists them under
  `constraints.placeholders`. Copy every placeholder exactly once and never type the protected
  text itself. The harness restores them before each gate and writes the final `output.txt`.
- **Plan.** `plan` in the task shows each row with only your ops and the number of output
  sentences the row must have after your pass (`target`). Rows are in output order; keep that
  order. A `keep` row must stay word for word.
- **Facts.** `state.facts` is frozen. Every gate checks its anchors; the last gate also needs a
  verdict per fact in the review file.
- **Fix rounds.** When a gate fails, the same pass comes back with `issues`. Fix only what they
  name; do not rework the rest.

## What each gate checks

- **Gate 3 (structure):** `pe check` against the original; each plan row has `target`
  sentences; `keep` rows are unchanged.
- **Gate 4 (lexis):** `pe check` against the original; the sentence count equals the previous
  pass; mode bands are reported (advisory).
- **Gate 5 (style):** `pe check` against the original; the plan's final sentence map; the length
  target when one was set; fact verdicts.

## Example (en, standard)

Original: "The report was written by the team, and it was published in March. Sales rose."
Plan: `[{"src": [1], "ops": ["split", "voice"], "target": 2}, {"src": [2], "ops": ["keep"], "target": 1}]`

- structure: "The report was written by the team. It was published in March. Sales rose."
- lexis: "The team wrote the report. It came out in March. Sales rose."
- style: unchanged here, since the plan lists no style ops and the mode is standard.
