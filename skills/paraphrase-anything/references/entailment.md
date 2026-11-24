# Entailment verdicts (last text gate)

The last text gate asks you to judge, pair by pair, whether the rewrite still means what the
original means. You judge; the harness checks that the judgement is complete and grounded.

## Steps

1. Write the rewrite (the task's `output`).
2. Run `python scripts/pe.py run pairs <session-dir>` to get the pairs for that rewrite.
3. Judge each pair in both directions and write the file named in `entailment.file`
   (`p5-style.nli.json` for the style pass).
4. Submit. If you change the rewrite later, run `pe run pairs` again: pairs follow the text.

## Pairs

- **With a plan** (`basis: plan`): one pair per plan row, id `r<row>`; the rewritten side is the
  output sentences the plan segmentation gives that row. Rows that drop everything have no pair.
- **Without a plan** (`basis: aligner`): pairs come from the deterministic aligner of `pe check`,
  ids `a1`, `a2`, ...; a merge or split shows up as one pair with several sentences.
- Pairs whose two sides are identical are skipped.
- `flags` lists `pe check` negation or hedge warnings on the pair's source sentences.
- `may_drop` is true for rows with the `shorten` op (or every pair in `shorten` mode without a
  plan).

## Format

```json
{"judge": "self",
 "pairs": [{"pair": "r1", "forward": "entail", "backward": "entail",
            "evidence": {"src": "rose by 5%", "rew": "went up by 5%"},
            "reason": ""}]}
```

- `forward`: does the original entail the rewrite? (The rewrite adds nothing.)
- `backward`: does the rewrite entail the original? (The rewrite loses nothing.)
- Each verdict is `entail`, `neutral`, or `contradict`.
- `evidence.src` and `evidence.rew` are short literal quotes from the pair's original and
  rewritten text: the part your verdict rests on. Whitespace may differ; words may not.
- `judge`: `self` when you judged your own rewrite, `independent` when a separate subagent that
  did not see `plan.json` or your drafts judged it from the pairs alone.

## What fails the gate

| Issue | Cause |
|-------|-------|
| `nli_file_missing`, `invalid_nli` | No file, bad JSON, no `pairs` list, or an unknown `judge`. |
| `nli_missing`, `nli_missing_verdict` | A pair without an entry, or without both verdicts. |
| `nli_unknown_pair`, `nli_duplicate_pair` | An id that is not in the pair list, or given twice. |
| `nli_evidence_not_found` | A quote that does not occur in its side of the pair. |
| `entailment_failed` | Any verdict other than `entail`, except the shortening rule below. |
| `nli_reason_required` | The pair has `flags` but both verdicts are `entail` and `reason` is empty. |

**Shortening:** when `may_drop` is true, `backward: neutral` passes if `reason` says what was
left out. `forward` must still be `entail`: shortening may lose content, never add it.

A failed pair means the rewrite changed the meaning: fix the rewrite, not the verdict. These
issues are errors and cannot be accepted.

## Limits

The harness cannot see who judged, so `judge` is reported as claimed (`judge_verified: false`).
Judging your own rewrite is weaker than an independent judge: authors tend to favour their own
text. Where the tool supports subagents, hand the pairs (not the plan) to one and ask for this
file. The evidence and warning rules make careless verdicts harder, not impossible.
