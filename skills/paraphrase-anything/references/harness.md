# Harness sessions (`pe run`)

In a harness session `pe` owns the workflow: it keeps the state, gives you exactly one task at a
time, and gates each pass against the original before moving on. You never choose the next step.

## Loop

```bash
python scripts/pe.py run init input.txt --mode standard     # prints the session directory
python scripts/pe.py run next <session-dir>                  # one task as JSON
# ... write the file named in "output" (and "review" when needed) ...
python scripts/pe.py run pairs <session-dir>                 # last pass: pairs to judge for entailment
python scripts/pe.py run submit <session-dir>                # gate: 0 pass, 1 fix needed, 2 error
# repeat next / submit until next returns {"step": "done"} or {"step": "incomplete"}
python scripts/pe.py run report <session-dir>                # what ran, what was skipped, what is open
```

`pe run init` options: `--mode`, `--persona` (a file in `references/personas/`), `--lang`
(default auto), `--passes` (comma list of `analysis`, `plan`, `structure`, `lexis`, `style`;
default all five), `--gates` (comma list of gate numbers, `""` for none; default all),
`--preset` (`fast`, `standard`, `strict`; see [presets](presets.md)), `--variants` (2–5 distinct
rewrites; needs pass `plan`), `--max-rounds` (fix rounds
per pass, default 2), `-o` (session directory; default a new temp directory). A final floor check
against the original runs in every configuration; `init` lists any `resolutions` it applied.
A `.md`, `.srt`, or `.vtt` input path starts a Files session; input over ~3,000 words starts a
Long session (chunk by chunk). See [routes](routes.md) for the task fields these routes add.
Other commands: `pe run status <session-dir>`, `pe run rewind <session-dir> --to <pass>`, and
`pe run pairs <session-dir>` (the entailment pairs of the last pass's current rewrite).

## The task

| Field | Meaning |
|-------|---------|
| `step`, `gate`, `pass` | The pass to do, its gate, and its position (e.g. `1/2`). |
| `checks` | What its gate runs: `full`, `floor` (last gate disabled), or `skipped`. |
| `inputs.original`, `inputs.previous` | The original, and the text this pass starts from. |
| `output` | The one file to write. Write nothing else in the session directory. |
| `instructions` | The only reference files to load for this pass. |
| `duties`, `ops`, `merged_passes` | What this pass is responsible for, including disabled passes merged into it. |
| `plan` | Text passes: each plan row with only this pass's ops and its sentence `target`. |
| `constraints` | Language, mode, persona, `protected` spans, `placeholders` to copy (text passes), and `length_ratio`. |
| `sentences` | The original's sentences with ids (JSON passes only). |
| `state.facts`, `state.analysis` | The frozen analysis (after pass 1). Every later gate re-checks the facts. |
| `round`, `max_rounds`, `issues` | Fix round, limit, and what the last failed gate found. |
| `review`, `review_required` | Optional review file for text passes; required items are listed. |
| `entailment` | Last pass: the verdicts file to write, the pair `basis` (`plan` or `aligner`), and the format. |

## Passes

- **analysis** (gate 1): write `analysis.json` (facts, constraints, discourse, register) as in
  [analysis](analysis.md); the task lists the original's `sentences` with ids.
  `constraints.keep` terms become protected spans and `constraints.length_ratio` is enforced at
  the last gate.
- **plan** (gate 2): write `plan.json`, one row per output unit covering every sentence once, as
  in [plan](plan.md).
- **structure**, **lexis**, **style** (gates 3–5): rewrite one layer at a time, as in
  [layers](layers.md). The first text pass starts from `masked.txt` (protected spans replaced by
  placeholders); each later one starts from the previous pass. Every gate restores the
  placeholders and runs `pe check` against the original; the last one writes the finished,
  restored rewrite to `output.txt`.

`analysis.json` and `plan.json` are **frozen** once their gate passes: editing them makes every
command exit 2. To change one, run `pe run rewind <session-dir> --to analysis` (or `--to plan`),
which discards that pass and every later artifact.

Text passes take an optional review file (`p5-style.review.json` for style, and so on) with
accepts and verdicts. When facts are frozen, the last text pass must give a verdict per fact:

```json
{"accept": [{"id": "w1", "reason": "double negative rewritten as a positive"}],
 "verdicts": [{"id": "f1", "verdict": "kept", "note": ""}]}
```

Warning ids come from the `issues` of the previous round. Errors cannot be accepted.

When its gate runs in full, the last text pass also needs entailment verdicts (`p5-style.nli.json`): run `pe run pairs`
after writing the rewrite and judge every pair in both directions, as in
[entailment](entailment.md). The report's `entailment` field records the pair basis, the count,
and the claimed `judge`.

## Rounds and endings

A failed gate sends the same pass back with its `issues`; `round` goes up by one. When a pass
fails after `max_rounds` fix rounds, the session ends **incomplete** and the report lists the
open issues. Say so to the user; never present an incomplete session as verified.

If `original.txt` in the session directory changes after `init`, every command exits 2: start a
new session.
