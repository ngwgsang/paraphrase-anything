# Readability lint (`pe lint`)

`pe lint` points at spots in a rewrite that hurt readability, so you revise those spots instead
of rewriting everything. It is advisory: findings are `warn` or `info`, the exit code is 0, and
no gate depends on it. It is a readability aid, not a way to make text pass as human-written.

```bash
python scripts/pe.py lint rewrite.txt --original original.txt
python scripts/pe.py lint --text "However, it failed. However, ..." --lang en
python scripts/pe.py lint rewrite.txt --rules my-rules/
```

With `--original`, phrase rules flag only what the rewrite introduced: a cliché the author already
used is not reported, and `connector_added` compares counts with the original (it is skipped
without one).

## Default rules (`lint.json`)

| Rule | Severity | Flags |
|------|----------|-------|
| `cliche` | warn | a phrase from the language's `cliches` list |
| `connector_repeat` | warn | the same connector again within `window` sentences |
| `connector_added` | info | a connector used more often than in the original |
| `dash_density` | info | dashes when there are more than `max_per_sentence` per sentence |
| `sentence_length_uniform` | info | all sentences about the same length (variation below `min_cv`) |

Clichés and connectors come from `lang/<code>.json` (`cliches`, `connectors`), so a language
adds them as data. Text inside code, URLs, and other protected spans is ignored.

## Output

```json
{"ok": true, "lang": "en", "counts": {"warn": 1, "info": 0},
 "findings": [{"id": "l1", "rule": "connector_repeat", "severity": "warn", "start": 20,
               "end": 27, "text": "However", "hint": "...", "sentences_apart": 1}],
 "rules_run": ["cliche", "connector_repeat", "..."], "skipped": []}
```

`start` and `end` are character offsets into the rewrite. Fix the flagged spot, keep everything
`pe check` protects, and do not chase zero findings: a repeated connector can be the right choice.

## Extra rules

`--rules DIR` loads every `*.json` in `DIR` after the defaults, in name order. Each file is
`{"rules": [...]}`; a rule with an existing `id` replaces it, and `"enabled": false` turns it off.

```json
{"rules": [
  {"id": "house_style", "kind": "phrases", "severity": "info",
   "phrases": {"en": ["utilize", "leverage"]}, "hint": "Prefer 'use'."},
  {"id": "dash_density", "enabled": false}
]}
```

Kinds: `phrases` (each occurrence), `repeat` (again within `window` sentences), `added` (more
than in the original), `density` (`chars`, `min_count`, `max_per_sentence`), and `uniformity`
(`min_sentences`, `min_cv`). Phrase kinds take `source` (a language data key) or `phrases` (a
list, or a map by language code).
