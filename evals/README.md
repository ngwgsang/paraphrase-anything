# Evaluation suite

```bash
python evals/run_evals.py                 # all cases, summary + per-language scores + gate
python evals/run_evals.py --lang vi       # one language
python evals/run_evals.py --thresholds my-gate.json --json out/report.json
```

Exit codes: `0` all cases pass and the gate passes, `1` a case or the gate fails, `2` usage or
input error. The JSON report (default `evals/report.json`, git-ignored) holds every case result,
the per-language scores, and the gate outcome.

Cases hold **fixed, pre-written** rewrites. The runner checks the tooling (`check`, `metrics`,
`protect`/`restore`, `extract`/`rebuild`, pairwise divergence) against them; it does not call an LLM.

## Cases

One JSON file per case in `cases/<lang>/NN-slug.json`; `id` must be `<lang>-NN-slug`.

| `category` | Required fields | Passes when |
|---|---|---|
| `prose`, `technical`, `academic`, `accept_warning` | `input`, `rewrite` | `check` is ok (after `accept`), invariants are present |
| `variants` | `input`, `variants` (≥ 2) | every variant passes `check`, no pair is too similar |
| `format` | `format` (`text`/`markdown`/`srt`/`vtt`), `input`, `segments` (`{id: text}`) | rebuild keeps everything outside the segments byte for byte, and the segment prose passes `check` |
| `check_fixture` | `input`, `rewrite`, `expect`, `note` | the `check` report matches `expect` |
| `triggers` | `prompts` (`prompt`, `expected_trigger`) | every prompt is classified as expected |

Optional fields: `mode` (enables band scoring), `accept` (`[{id, reason}]`), `expected_invariants`
(`numbers`, `code`, `urls`, `terms`: literal strings that must appear in the rewrite, or in the
whole rebuilt file for `format` cases), `format: "structured"` with `masked_rewrite` (protect/restore
round trip), `expected_output` (exact rebuilt file).

`expect` lists the outcome `check` must produce: `ok`, and the exact sets of error and warning
`type`s. Use it both for true positives (a changed number must raise `number_missing` /
`number_extra`) and for known false positives (a correct antonym rewrite raises
`negation_mismatch`), so a change in `check` behaviour shows up as a fixture mismatch.

## Scores per language

| Score | Meaning |
|---|---|
| `pass_rate` | cases that pass |
| `check_pass_rate` | rewrite, variant, and format cases whose `check` is ok |
| `accepted_warning_rate` | of those, the share that needed at least one accepted warning (false-positive load) |
| `band_rate` | cases with a `mode` whose overlap is within the band (advisory, not gated) |
| `variant_overlap` | mean pairwise overlap of variant sets (lower = more diverse) |
| `trigger_accuracy` | prompts classified correctly by the trigger heuristic |
| `fixture_accuracy` | `check_fixture` cases whose outcome matches `expect` |

## Gate

`thresholds.json` maps `min_<score>` / `max_<score>` to a limit applied to every language. A score
that was not measured for a language (`null`) is skipped. Use the gate as the decision point for
later features: a change such as parallel chunking ships only if the gate still passes.
