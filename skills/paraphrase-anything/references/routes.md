# Routes inside a session

`pe run init` picks the route from the input; the tasks then tell you what to do. This page
explains the extra task fields each route adds.

## Files (any [format](formats.md) but `.txt`)

`pe run init notes.md` detects the format from the extension. The session's `original.txt` is
the file's **prose only**: one block per segment (heading, paragraph, list item, subtitle cue),
separated by blank lines. Code, tables, front matter, HTML, and subtitle timings never reach you.

- `constraints.segments` is the number of blocks. Keep exactly that many blank-line separated
  blocks, in order; never merge two blocks or split one (`segment_count_changed`). Sentences may
  still be split or merged **inside** a block.
- Plan rows must not merge sentences from different blocks.
- When the session completes, the harness rebuilds the file around your prose: `output<ext>` (the
  format's extension, e.g. `output.md`) next to `output.txt`. Copy it to `name.paraphrased<ext>` for the user.
- For subtitles keep each cue short; timings and numbering are kept for you.

## Long (over ~3,000 words)

`init` reports `"long": true`. Each text pass is done **one chunk at a time**:

- The task has `chunk: {"index", "of"}`, `inputs.previous` (the chunk to start from), and
  `output` (the chunk file to write, e.g. `p5-style.chunks/002.md`). Write the whole chunk, then
  `pe run submit`; the next task is the next chunk.
- `context.previous_rewritten` is the last paragraph you wrote for the chunk before: read-only
  context for continuity. Never summarise: later chunks get the same care as the first.
- `plan` lists only the rows of this chunk; `placeholders` only the ones in this chunk.
- `constraints.glossary` holds the glossary from pass 1 (`analysis.json` may give `glossary`
  entries chosen from `glossary_candidates`: `decision` `keep` or `rewrite-consistently` with a
  `rendering`). Without one, recurring names and acronyms must be kept.
- The gate runs once every chunk is in, on the merged text. If it fails, the next task has
  `chunk.fix: true` and `chunk_files`: edit only the chunks the issues point to, then submit.
- At the last pass, write every chunk file, then run `pe run pairs` before submitting the last
  chunk: the entailment pairs cover the whole text.
- In pass 2, `chunks` lists the sentence ids of each chunk: plan rows may not cross a chunk
  (`plan_crosses_chunk`) or go back to an earlier chunk (`plan_chunk_order`).

## Variants (`--variants N`)

`pe run init input.txt --variants 3` asks for N distinct rewrites; it needs pass `plan`.

- Pass 2 writes one plan per variant, each with its own `axis`:
  `{"variants": [{"axis": "structure", "rows": [...]}, {"axis": "register", "rows": [...]}]}`.
  Axes must differ (see [variants](variants.md)).
- Each text pass then runs once per variant: the task's `variant` gives its id, index, and axis,
  and the files carry the id (`p5-style.v2.txt`, `p5-style.v2.nli.json`).
- After the last variant passes its last gate, a pairwise gate (`gv`) compares every pair. A
  pair that is too similar sends the later variant back with `variants_too_similar`: rewrite it
  along its axis, further from the other one.
- Outputs are `output.v1.txt`, `output.v2.txt`, ...; the report lists them under `variants`.

Variants of a long text are not supported in one session: rewrite it once, or split it first.
