# Language packs

A language is added with data files only; no Python code changes. A pack is:

- `lang/<code>.json`: markers, terminators, separators, detection rule, and fixtures;
- `references/languages/<code>.md`: the note the agent reads (register, pronouns, pitfalls),
  starting with a `- **Table headers:** A · B · C` line for the response table.

```bash
python scripts/pe.py lang new ko --name 한국어            # word-based script
python scripts/pe.py lang new th --name ไทย --unit char   # no spaces between words
python scripts/pe.py langs                                 # tier, checks, open problems
```

## Tiers

| Tier | Meaning |
|------|---------|
| 0 | Generic fallback: no pack, or a pack whose schema or fixtures fail (`pe langs` lists the problems). |
| 1 | Data-only pack: schema valid, fixtures pass, language note present. |
| 2 | Tier 1 plus at least 10 eval cases in `evals/cases/<code>/`. |

The test suite requires every installed pack to be at least tier 1, so a pack is registered
once its fixtures pass.

## Data keys

| Key | Meaning |
|-----|---------|
| `code`, `name` | Code (must match the file name) and display name. |
| `length_unit` | `word` (space-separated) or `char` (counts characters). |
| `match` | `word` (markers match whole words; `*` at an end allows a prefix/suffix) or `substring`. |
| `has_case` | Whether capitalised words are proper-noun candidates. |
| `sentence_terminators`, `abbreviations` | Sentence splitting. Full-width terminators split at once. |
| `negation_markers`, `hedge_markers` | Compared between original and rewrite by `pe check`. |
| `decimal_separator`, `thousands_separator` | Number normalisation. |
| `detect_words` | Common words that score Latin-script text for this language. |
| `detect` | `script` (regex character class), `priority`, `min_share`, `latin_fallback` (see below). |
| `cliches`, `subtitle` | Clichés to avoid (`pe lint`); subtitle limits (`max_line_chars`, `max_cps`). |
| `connectors` | Optional. Discourse connectors that `pe lint` watches for repetition and additions. |
| `fixtures` | `detect` (sample texts), `sentences` (`{text, count}`), `negation`, `hedge` (samples that contain a marker). |

## Detection

`pe detect` tries packs with a `detect.script` rule by descending `priority`: a pack wins when
its script occurs at least `min_share` times the number of Latin letters (`0` = any occurrence).
Text dominated by an unclaimed non-Latin script is `default`. Latin text is scored with
`detect_words`; ties and zero scores go to the `latin_fallback` pack.

Current rules: ja (kana, priority 30), zh (Han, priority 20, `min_share` 1), vi (Vietnamese
letters, priority 10), en (`latin_fallback`). A distinctive script outranks a shared one, so
Japanese text with kana is never detected as Chinese.

## Hooks

en, vi, ja, and zh needed no code hooks, so there is no hook interface yet. Add one only when a
language cannot be expressed as data (for example a dictionary-based word splitter); it would
live in an optional extra, never in core.
