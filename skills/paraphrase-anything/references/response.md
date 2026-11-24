# Response format

Use this layout for every answer after verification. Write all labels in the user's language.

## Layout

1. **The rewrite**, inside a plain-text code block (see below) so the user can copy it.
2. **What changed**: a table (below).
3. **Verification**: one line, e.g. "Checked: numbers, citations, links and code unchanged."
   List remaining warnings honestly. If key facts were used, add "Key facts: N/N kept" and
   list any fact that is still `changed` or `lost`. After a harness session, name the report's
   `skipped_checks`, e.g. "Skipped: entailment, length target." (see [presets](presets.md)).
4. **Follow-ups**: suggested next requests (below).

## The rewrite block

Put the rewritten text, and nothing else, in a fenced block tagged `text`:

````
```text
The rewritten text goes here, exactly as the user should paste it.
```
````

- No labels, quotes, bold, or commentary inside the block; only the text to copy.
- Keep the input's own formatting inside the block (Markdown, line breaks, lists), unrendered.
- If the rewrite itself contains a triple-backtick fence, open and close the block with four
  backticks instead, so the inner fence does not end it early.
- Place a one-line heading before the block only when needed (for variants, see below).

## What changed table

| Original | Rewritten | Change |
|----------|-----------|--------|
| "was published in 2024" | "came out in 2024" | word choice |
| "A, because B." | "Since B, A." | structure |

Rules:
- **Quote verbatim.** Each cell is a fragment copied exactly from the original or the rewrite.
  Never paraphrase inside the table; the reader must be able to find it in both texts.
- **One row per meaningful change.** Group trivial synonym swaps into one row; skip text that
  stayed the same. Aim for 3–8 rows; for long texts show the most significant changes and say
  how many more there were.
- **Fragments, not paragraphs.** Quote the changed phrase (a few words to one clause). Quote a
  whole sentence only when it was restructured.
- **Change column:** a short label such as word choice, structure, voice, register, concision,
  or added/removed detail. Do not justify at length.
- Never list numbers, names, code, or links as changed: if one changed, that is an error to fix.
- Very short input (one sentence): a table of 1–3 rows is fine; do not pad it.
- When the result is written to a file, show the table in the chat, not in the file.

Header labels: use the **Table headers** line of the language note
(`references/languages/<code>.md`). For a language without a note, translate
"Original · Rewritten · Change".

## Variants

Label each variant with its axis (see [variants](variants.md)) in a heading, then give each
variant its own `text` block (so each can be copied alone) followed by its own small table.
Close with one verification line covering all variants.

## Follow-ups

End with 2–4 short suggestions of what the user could ask next, phrased as requests they can
copy, in the user's language. Tailor them to the text and the request:
- Offer a different mode or tone than the one just used (shorter, more formal, more casual,
  closer to the original, bolder rewrite).
- Offer variants if only one version was given; offer to apply the same style to another part
  of the text if it was long.
- Offer a targeted tweak when the table shows a risky change (for example "keep the original
  wording of the second sentence").
- Do not suggest the mode already used, translation, or anything that evades plagiarism or
  AI-detection tools. Do not act on the suggestions until the user picks one.

Example (en), after the rewrite block and table:

> **Want to go further?** Make it about 30% shorter · Give me 3 variants in different tones ·
> Keep the original wording of the first sentence
