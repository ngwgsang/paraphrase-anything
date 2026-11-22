# Preservation rules

What must survive a paraphrase, and how `pe` enforces it.

## Masked by `pe protect` (never visible to you as text)
Code blocks, inline code, URLs, Markdown link targets, emails, LaTeX, HTML tags, and any term
passed with `--keep`. They become `⟦Pn⟧` placeholders.

- Keep every placeholder **exactly once**. Do not translate, split, or re-number it.
- When you reorder a sentence, move the placeholder with the phrase it belongs to.
- Keep Markdown link text readable: `[the docs](⟦P2⟧)`; rewrite the link text, not the target.

## Kept readable but verified by `pe check`
| Item | Severity | Notes |
|------|----------|-------|
| Numbers, dates, units, percentages | error | compared by value, order-independent; keep digits as digits |
| Citations `[1]`, `[2, 3]`, `(Smith, 2020)` | error | keep them attached to the claim they support |
| Protected spans (code, URLs, …) | error | must match the original exactly |
| Negation (`not`, `không`, `ない`, …) | warning | count per aligned sentence; antonym rewrites may be accepted |
| Hedges (`may`, `có thể`, `かもしれない`, …) | warning | do not turn "may" into "will" or drop "about" / "khoảng" / "約" |
| Proper nouns | warning | capitalised names (en, vi); unsupported for ja |
| Omitted / added sentences | warning | `sentence_unaligned`, `sentence_added` |

## Also keep (not machine-checked)
For long or high-stakes text, list the load-bearing ones as key facts and verify them: see [facts](facts.md).

- Direct quotations: copy verbatim inside quotation marks.
- Defined terms and acronyms: use the same rendering every time.
- Modality and certainty: "must" ≠ "should" ≠ "may".
- Scope words: "all", "some", "only", "at least", "up to", "nearly".
- Formatting: headings, list structure, tables, emphasis, line breaks, front matter.
- Register markers the user relies on (honorifics, pronoun choice) unless the tone change asks
  otherwise.

## Accepting a warning
Accept only when meaning is unchanged, and say why in the reason, e.g.:

```json
[
  {"id": "w1", "reason": "double negative 'not uncommon' rewritten as 'common'"},
  {"id": "w3", "reason": "sentence merged into previous one; content preserved"}
]
```

Errors cannot be accepted. Fix them.
