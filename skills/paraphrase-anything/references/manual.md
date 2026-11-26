# Manual routes (fallback)

Use these steps only when a harness session cannot run: for example the tool cannot keep files
between commands, or `pe run init` exits 2 for an input it does not support. The harness route
in SKILL.md is the default because it keeps state, gates every pass, and reports what was skipped.
When you fall back, say so in the verification line ("Checked manually: ...").

All paths below are inside your temp folder; `original.txt` is the pinned original.

## Key facts (long or high-stakes text)

If the text is over ~150 words, or the user wants strict or exact meaning, list the 3–8 facts
that must survive (one short claim each, with literal `anchors`) in `facts.json`, then run
`pe facts original.txt --facts facts.json`. Details and formats: [facts](facts.md).

## Simple

Short plain prose (under ~300 words, no code, URLs, math, or HTML).
1. Rewrite directly.
2. Save the rewrite to `rewrite.txt` and run `pe check original.txt rewrite.txt`.

## Structured

Contains code, inline code, URLs, LaTeX, or HTML, or the user names terms to keep.
1. `pe protect original.txt -o masked.txt --map map.json [--keep "Term"]`
2. Rewrite `masked.txt`. Keep every `⟦Pn⟧` placeholder exactly once; move it with its phrase
   if the sentence is reordered.
3. `pe restore masked-rewrite.txt --map map.json -o rewrite.txt`. Fix any reported placeholder issue.
4. `pe check original.txt rewrite.txt [--keep "Term"]`

## Files

A file in any [format](formats.md) other than plain text, or any document where only the prose should change.
1. `pe extract notes.md -o segments.json` lists the rewritable segments (`id`, `text`). Code,
   tables, front matter, HTML, and subtitle indices and timings are never listed.
2. Rewrite each `text` in `segments.json`, keeping every `id`. Segments that contain inline code
   or URLs follow the Structured route. For subtitles keep lines short and the meaning per cue.
3. `pe rebuild notes.md --segments segments.json -o notes.paraphrased.md` puts the texts back and
   keeps line endings. For `.srt`/`.vtt` it also reports advisory line-length and reading-speed
   warnings (`--max-line-chars`, `--max-cps` override the per-language defaults).
4. `pe check notes.md notes.paraphrased.md`.

## Long

Over ~3,000 words (~6,000 characters for Japanese). Process chunks one after another.
1. If the text has code, URLs, or LaTeX, run `pe protect` first (Structured route).
2. `pe chunk masked.txt -o chunks/` writes `001.md`, `002.md`, ... and `manifest.json`
   (`needs_chunking` is false below the threshold; then use the Simple or Structured route).
3. `pe glossary masked.txt -o glossary.json [--keep "Term"] [--term "Term"]`. For each entry set
   `decision` to `keep` or `rewrite-consistently` and give a `rendering` for the latter.
4. For each chunk in order, rewrite it into `rewritten/NNN.md` (same file name). Give yourself
   the glossary and the last paragraph of the previous rewritten chunk as read-only context.
   Never summarise: later chunks get the same care as the first.
5. `pe merge chunks/ --rewritten-dir rewritten/ -o masked-rewrite.txt`, then `pe restore` if you
   protected, and `pe check original.txt rewrite.txt`.
6. `pe glossary masked.txt --glossary glossary.json --rewritten masked-rewrite.txt` reports
   lost terms and inconsistent renderings. Fix those sentences like check warnings.

## Variants

N versions requested.
1. Give each variant a different axis so they differ in substance, not just synonyms; see
   [variants](variants.md).
2. Check every variant on its own with `pe check`.
3. `pe metrics --pairwise v1.txt v2.txt v3.txt` (or `--pairwise --variant "v1" --variant "v2"`
   for raw text). For each pair in `too_similar`, rewrite the weaker one along a different axis
   (at most one extra round).

## Verify and fix

`pe check` returns `errors`, `warnings`, `unsupported`:

- **Errors** (numbers, citations, protected spans, leftover placeholders) must be fixed. Edit
  only the affected sentence, then re-run.
- **Warnings** (negation or hedge count changed, proper noun missing, sentence dropped or added):
  look at the quoted `original` and `rewritten` text. If meaning really changed, fix the
  sentence. If the change is legitimate (e.g. "not uncommon" → "common"), accept it with a
  reason: write `[{"id": "w1", "reason": "double negative rewritten as positive"}]` to
  `accept.json` and re-run with `--accept accept.json`.
- **unsupported** lists checks the language data cannot run; review those aspects yourself.

If you extracted facts, also run `pe facts original.txt rewrite.txt --facts facts.json
--verdicts verdicts.json`: it checks the anchors and that you judged every fact `kept`,
`changed`, or `lost`. Fix `changed` and `lost` facts like errors.

Optionally run `pe metrics original.txt rewrite.txt --mode <mode>` for divergence and length.
Bands are advisory. For explicit length targets use `--target-ratio 0.7`; that one is enforced
(±10%). Stop after **2 fix rounds**; if issues remain, say exactly which ones.
