# Presets, passes, and gates

A harness session (`pe run init`) runs up to five passes, each followed by its gate. Choose a
preset, or pick passes and gates yourself; explicit `--passes` and `--gates` override the preset.
Without a preset or flags, every pass and gate runs.

| Preset | Passes | Gates | Judge | Use when |
|--------|--------|-------|-------|----------|
| `fast` | style | none | self | the user asks for speed over verification (no entailment gate) |
| `standard` | plan, lexis, style | g2, g4, g5 | self | most rewrites, including a single sentence |
| `strict` | analysis, plan, structure, lexis, style | g1, g2, g3, g4, g5 | independent | "keep the exact meaning", legal, medical, or other high-stakes text |

`presets.json` (next to `modes.json`) holds the same values; a test keeps this table in sync.

```bash
python scripts/pe.py run init input.txt --preset standard
python scripts/pe.py run init input.txt --passes analysis,plan,style --gates 1,2,5
python scripts/pe.py run init input.txt --preset strict --gates ""
```

## Passes and gates

- **Disabling a pass** merges its ops into the next enabled text pass (see [layers](layers.md)).
- **Disabling a gate** skips that verification only; the pass still runs.
- `--gates` takes numbers (`1,3,5`) or ids (`g1,g3,g5`); `""` disables every gate. Unknown ids
  exit 2.

## The floor

A final check against the original **always** runs after the last pass, even with `--gates ""`:
`pe check` errors (numbers, citations, protected spans, placeholders), and, when pass 1 ran, the
frozen fact anchors and a verdict per fact. When gate 5 is enabled the floor is part of it; when
it is disabled the floor runs alone and the task says `"checks": "floor"`.

## Resolutions

Some requests depend on passes that are off. The harness resolves them the same way every time
and lists each one under `resolutions` in `session.json`, the `init` output, and the report:

| Situation | Resolution |
|-----------|------------|
| Gate of a disabled pass requested | `dropped` |
| Pass `analysis` or `plan` enabled, its gate not requested | `kept`: later passes rely on its file |
| Last gate disabled | `floor`: the floor check runs instead |
| Last gate enabled, pass `plan` disabled | `aligner`: entailment pairs come from the `pe check` aligner |

## Reporting what was skipped

`report.json` lists `gates_run` (the floor appears as `floor`), `gates_skipped`, `resolutions`,
and `skipped_checks`, for example `["key facts", "check warnings", "length target",
"entailment"]`. Name the skipped checks in the verification line of the response:
"Checked: numbers, citations, links and code unchanged. Skipped: entailment, length target."
