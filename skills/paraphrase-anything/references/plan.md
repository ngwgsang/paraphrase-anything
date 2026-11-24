# Pass 2: plan (`plan.json`)

Commit to what you will change in each original sentence before rewriting. Later passes apply
the plan, and later gates check the rewrite against it, so plan only what you will do.

```json
{
  "rows": [
    {"src": [1], "ops": ["split", "lexical"], "target": 2},
    {"src": [2, 3], "ops": ["merge", "voice"], "target": 1},
    {"src": [4], "ops": ["keep"], "target": 1}
  ],
  "axis": "Structure"
}
```

- **One row per output unit, in output order.** `src` lists the original sentence ids (from the
  task's `sentences`) the row rewrites; every sentence appears in exactly one row.
- **`ops`** is a non-empty subset of:

  | Op | Meaning |
  |----|---------|
  | `keep` | Leave the sentence as it is (only op in its row). |
  | `split` | One sentence becomes several (`target` ≥ 2). |
  | `merge` | Several `src` sentences become one (`target` = 1); required when `src` has 2+ ids. |
  | `reorder` | Move clauses or the sentence itself. |
  | `voice` | Active ↔ passive. |
  | `clause` | Restructure clauses inside the sentence (subordinate ↔ main, nominalisation). |
  | `lexical` | Replace words and phrases. |
  | `register` | Change tone or formality. |
  | `shorten` / `expand` | Make it shorter or longer. |

- **`target`**: the number of output sentences for the row: 1, or ≥ 2 with `split`. `0` means
  the content is dropped and is allowed only with `shorten` in `shorten` mode.
- **`axis`** (optional): the variant axis this plan follows (see [variants](variants.md)).

Gate 2 fails on uncovered or double-covered sentences, unknown sentence ids or ops, `keep`
combined with other ops, `split` together with `merge`, targets that do not match the ops, and
length plans that contradict the goal: `shorten` mode or a `length_ratio` below 1 needs at least
one `shorten` op and no `expand`, and the reverse for longer results. In `light` mode,
structural ops (`split`, `merge`, `reorder`) are reported as advisory warnings.

## Examples

**en** (standard): "The report was written by the team. It was published in March."

```json
{"rows": [{"src": [1, 2], "ops": ["merge", "voice"], "target": 1}]}
```

→ "The team wrote the report, which came out in March."

**vi** (shorten): "Theo báo cáo, doanh thu tăng 12%. Đây là một kết quả rất đáng mừng đối với công ty."

```json
{"rows": [{"src": [1], "ops": ["lexical"], "target": 1},
          {"src": [2], "ops": ["shorten"], "target": 0}]}
```

**ja** (standard): 「新製品は軽量で、価格も安く、電池が長持ちする。」

```json
{"rows": [{"src": [1], "ops": ["split", "lexical"], "target": 2}]}
```

→ 「新製品は軽くて安い。電池の持ちも良い。」
