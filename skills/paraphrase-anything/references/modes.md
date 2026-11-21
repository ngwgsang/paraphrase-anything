# Modes

Each mode sets how far the rewrite may move from the original. Overlap bands come from
`scripts/paraphrase_everything/modes.json` and are **advisory**: use them as a signal, never
swap words just to hit a number. Only `--target-ratio` is enforced.

| Mode | Overlap band | Length ratio | Use when |
|------|--------------|--------------|----------|
| `light` | 0.45–0.85 | 0.90–1.10 | polish wording, keep structure ("reword slightly", "smooth this out") |
| `standard` | 0.15–0.45 | 0.85–1.15 | default paraphrase ("paraphrase", "rewrite", "viết lại") |
| `creative` | 0.00–0.20 | 0.70–1.30 | fresh structure and phrasing ("completely rewrite", "make it original") |
| `shorten` | — | user target ±10% | "shorter", "trim to 70%", "condense" (not a summary: keep every fact) |
| `expand` | — | 1.15–2.00 | "longer", "more detailed": add clarity and connectives, **no new facts** |

## light
- Keep sentence order and most structure.
- Change word choice, smooth transitions, fix awkward phrasing.
- Good for emails and documents the user mostly likes.

## standard
- Change sentence structure as well as wording: reorder clauses, merge or split sentences,
  switch active and passive voice where natural.
- Keep paragraph order and the overall argument flow.

## creative
- Restructure freely within each paragraph; you may reorder sentences when logic allows.
- Vary rhythm and sentence length; pick fresh phrasing over safe synonyms.
- Still no new facts, examples, or opinions.

## shorten
- Remove redundancy, filler, and repetition; combine sentences.
- Keep every number, name, citation, and claim. If the target is impossible without dropping
  facts, say so and give the shortest faithful version.
- Verify with `pe metrics original.txt rewrite.txt --target-ratio <r>`.

## expand
- Make implicit links explicit, add connectives and clarifying phrasing.
- Never invent data, sources, or examples. `pe check` flags `sentence_added`; accept it only
  when the added sentence restates existing content.

## Tone on top of a mode
Tone (formal, casual, academic, simple / plain language) is independent of mode.
- **formal:** no contractions or slang, precise vocabulary, complete sentences.
- **casual:** contractions, shorter sentences, conversational connectives.
- **academic:** hedged where the original hedges, discipline terms kept, impersonal voice.
- **simple:** short sentences, common words, one idea per sentence; keep technical terms the
  reader needs and explain them only if the original does.
