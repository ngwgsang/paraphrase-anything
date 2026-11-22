---
name: paraphrase-anything
description: Paraphrase, rewrite, or reword any text in a chosen tone (formal, casual, academic, simple, shorter, longer) or produce several distinct variants, while keeping numbers, names, citations, code, links, and meaning exactly intact, verified by deterministic checks. Use when the user asks to paraphrase, rewrite, reword, rephrase, restate, "say this differently", give alternative versions or variants, viết lại, diễn đạt lại, paraphrase lại, 言い換え, 書き換え, for pasted text or a .txt / .md file. Do not use for pure summarisation, translation into another language, or proofreading-only requests.
---

# Paraphrase Anything

Rewrite text in the requested style while the **original stays the single source of truth**.
You write; the bundled `pe` tool verifies. Never grade your own rewrite by eye alone.

`pe` is zero-install (Python ≥ 3.9 standard library). Run it as:

```bash
python <skill-dir>/scripts/pe.py <command> ...    # use python3 if python is not Python 3
```

All commands print JSON. Exit code `0` = ok, `1` = issues found, `2` = usage/input error.

## Workflow

### 1. Pin the original
Save the user's text **verbatim** to a temp file (outside the user's project), e.g.
`<tmp>/pe-<short-id>/original.txt`. Never edit this file. Every check compares against it.

### 2. Resolve the request
| Setting | Default | Notes |
|---------|---------|-------|
| mode | `standard` | `light`, `standard`, `creative`, `shorten`, `expand`; see [modes](references/modes.md) |
| language | same as input | if the user wants another language, that is translation; ask first |
| length | about the same | "shorter / 70%" → `shorten` with a target ratio |
| variants | 1 | "give me 3 versions" → variants flow |
| tone / persona | none | formal, casual, academic, simple; apply within the chosen mode |

Load only what you need: [modes](references/modes.md), [variants](references/variants.md), [preservation rules](references/preservation.md), [response format](references/response.md),
and the language note for the input language: [en](references/languages/en.md),
[vi](references/languages/vi.md), [ja](references/languages/ja.md).

### 3. Pick a route

**Simple:** short plain prose (under ~300 words, no code, URLs, math, or HTML).
1. Rewrite directly.
2. Save the rewrite to `rewrite.txt` and run `pe check original.txt rewrite.txt`.

**Structured:** contains code, inline code, URLs, LaTeX, or HTML, or the user names terms to keep.
1. `pe protect original.txt -o masked.txt --map map.json [--keep "Term"]`
2. Rewrite `masked.txt`. Keep every `⟦Pn⟧` placeholder exactly once; move it with its phrase
   if the sentence is reordered.
3. `pe restore masked-rewrite.txt --map map.json -o rewrite.txt`. Fix any reported placeholder issue.
4. `pe check original.txt rewrite.txt [--keep "Term"]`

**Long:** over ~3,000 words. Until chunking ships, work section by section (split at headings
or paragraphs), keep a running list of key terms and how you render them, and use the
Structured or Simple route for each section. Then run `pe check` on the reassembled text.

**Variants:** N versions requested.
1. Give each variant a different axis so they differ in substance, not just synonyms:
   structure (reorder, merge, split), register (more formal or more casual), concision,
   voice (active or passive), vocabulary. Choose axes that fit the mode; see [variants](references/variants.md).
2. Check every variant on its own with `pe check`.
3. `pe metrics --pairwise v1.txt v2.txt v3.txt` (or `--pairwise --variant "v1" --variant "v2"` for raw text).
   For each pair in `too_similar`, rewrite the weaker one along a different axis (at most one extra round).

### 4. Verify and fix
`pe check` returns `errors`, `warnings`, `unsupported`:

- **Errors** (numbers, citations, protected spans, leftover placeholders) must be fixed. Edit
  only the affected sentence, then re-run.
- **Warnings** (negation or hedge count changed, proper noun missing, sentence dropped or added):
  look at the quoted `original` and `rewritten` text.
  - If meaning really changed → fix the sentence.
  - If the change is legitimate (e.g. "not uncommon" → "common") → accept it with a reason:
    write `[{"id": "w1", "reason": "double negative rewritten as positive"}]` to `accept.json`
    and re-run with `--accept accept.json`.
- **unsupported** lists checks the language data cannot run; review those aspects yourself.

Optionally run `pe metrics original.txt rewrite.txt --mode <mode>` for divergence and length.
Bands are advisory: `above` in standard mode means you stayed close to the original, so rewrite
more only if the user wanted a real paraphrase. Do not swap words just to move a number.
For explicit length targets use `--target-ratio 0.7`; that one is enforced (±10%).

Stop after **2 fix rounds**. If issues remain, say exactly which ones.

### 5. Respond
Follow [response](references/response.md). In short, answer with:
1. The rewrite (each variant labelled with its axis) in a plain-text ```text block, so it can be
   copied as is. Keep the input's formatting inside the block.
2. A **What changed** table of verbatim `Original | Rewritten | Change` fragments.
3. One verification line, e.g. "Checked: numbers, citations, links and code unchanged."
   List any remaining warnings honestly. Do not paste the JSON.
4. 2–4 **follow-up suggestions** the user can copy as their next request.

If the input is a file, write the result to a new file next to it (e.g. `name.paraphrased.md`)
unless the user asked to overwrite; show the table and follow-ups in the chat only.

## Hard rules
- Never change facts, numbers, dates, names, quotes, citations, code, or links.
- Never add claims, examples, or opinions that are not in the original.
- Keep digits as digits; "3" → "three" is reported as a number error.
- Keep the input language and formatting (Markdown structure, lists, line breaks).
- Do not present the output as a way to evade plagiarism or AI-detection tools.
