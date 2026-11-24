# Harness sessions (`pe run`)

In a harness session `pe` owns the workflow: it keeps the state, gives you exactly one task at a
time, and gates each pass against the original before moving on. You never choose the next step.

## Loop

```bash
python scripts/pe.py run init input.txt --mode standard     # prints the session directory
python scripts/pe.py run next <session-dir>                  # one task as JSON
# ... write the file named in "output" (and "review" when needed) ...
python scripts/pe.py run submit <session-dir>                # gate: 0 pass, 1 fix needed, 2 error
# repeat next / submit until next returns {"step": "done"} or {"step": "incomplete"}
python scripts/pe.py run report <session-dir>                # what ran, what was skipped, what is open
```

`pe run init` options: `--mode`, `--persona` (a file in `references/personas/`), `--lang`
(default auto), `--passes` (comma list; default all available), `--max-rounds` (fix rounds per
pass, default 2), `-o` (session directory; default a new temp directory).
Other commands: `pe run status <session-dir>` and `pe run rewind <session-dir> --to <pass>`.

## The task

| Field | Meaning |
|-------|---------|
| `step`, `gate`, `pass` | The pass to do, its gate, and its position (e.g. `1/2`). |
| `inputs.original`, `inputs.previous` | The original, and the text this pass starts from. |
| `output` | The one file to write. Write nothing else in the session directory. |
| `instructions` | The only reference files to load for this pass. |
| `duties`, `merged_passes` | What this pass is responsible for, including duties of disabled passes. |
| `constraints` | Language, mode, persona, `protected` spans to keep verbatim, and `length_ratio`. |
| `sentences` | The original's sentences with ids (JSON passes only). |
| `state.facts`, `state.analysis` | The frozen analysis (after pass 1). Every later gate re-checks the facts. |
| `round`, `max_rounds`, `issues` | Fix round, limit, and what the last failed gate found. |
| `review`, `review_required` | Optional review file for text passes; required items are listed. |

## Passes available now

- **analysis** (gate 1): write `analysis.json` (facts, constraints, discourse, register) as in
  [analysis](analysis.md); the task lists the original's `sentences` with ids. Once gate 1
  passes the file is **frozen**: editing it makes every command exit 2. To change it, run
  `pe run rewind <session-dir> --to analysis`, which discards every later artifact.
  `constraints.keep` terms become protected spans and `constraints.length_ratio` is enforced at
  the last gate.
- **plan** (gate 2): write `plan.json`, one row per output unit covering every sentence once, as
  in [plan](plan.md).
- **style** (gate 5): write the finished rewrite to `p5-style.txt`. The gate runs `pe check`
  against the original and, when facts are frozen, checks every anchor and requires a verdict
  per fact. Put accepts and verdicts in `p5-style.review.json`:

```json
{"accept": [{"id": "w1", "reason": "double negative rewritten as a positive"}],
 "verdicts": [{"id": "f1", "verdict": "kept", "note": ""}]}
```

Warning ids come from the `issues` of the previous round. Errors cannot be accepted.

## Rounds and endings

A failed gate sends the same pass back with its `issues`; `round` goes up by one. When a pass
fails after `max_rounds` fix rounds, the session ends **incomplete** and the report lists the
open issues. Say so to the user; never present an incomplete session as verified.

If `original.txt` in the session directory changes after `init`, every command exits 2: start a
new session.
