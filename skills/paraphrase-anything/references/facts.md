# Key facts

A short checklist of the claims that must survive the rewrite. You list them before rewriting;
`pe facts` checks what code can, and you judge the rest. Use it when the text is over about 150
words, when meaning is high-stakes, or when the user asks for strict or exact meaning. Skip it
for short text.

## Writing the list

Keep it **short and focused**:
- One claim per fact, a plain statement of at most 120 characters. No advice, no rewording.
- Only load-bearing claims (who did what, numbers, cause and effect, conditions, scope words
  such as "all / some / only / at least"). Not a restatement of every sentence.
- Aim for 3–8 facts; the hard cap is 12 (`--max-facts`). For long texts, one list per section.
- Each fact has 0–3 `anchors`: literal values copied from the original (a number, a name, a
  quoted term). Anchors are what code verifies, so prefer values the rewrite must keep
  verbatim. Never use ordinary words the rewrite may legitimately replace.

`facts.json`:

```json
[
  {"id": "f1", "fact": "The team had 42 members in 2024", "anchors": ["42", "2024"]},
  {"id": "f2", "fact": "Acme funded the study", "anchors": ["Acme"]},
  {"id": "f3", "fact": "Renewable energy reduces emissions only in industry", "anchors": []}
]
```

## Steps

1. **Validate** before rewriting. This catches invented facts (an anchor that is not in the
   original) and lists that are too long or too big:
   ```bash
   pe facts original.txt --facts facts.json
   ```
2. Rewrite as usual (see the routes in SKILL.md).
3. **Verify** anchors in the rewrite (numbers by value, names and terms as whole words):
   ```bash
   pe facts original.txt rewrite.txt --facts facts.json
   ```
4. **Judge each fact** against the rewrite and write `verdicts.json`; one entry per fact:
   `kept` (same meaning, wording may differ), `changed` (meaning shifted), `lost` (missing).
   Add a short `note` for anything that is not `kept`.
   ```json
   [{"id": "f1", "verdict": "kept"}, {"id": "f3", "verdict": "changed", "note": "now says 'all sectors'"}]
   ```
   ```bash
   pe facts original.txt rewrite.txt --facts facts.json --verdicts verdicts.json
   ```
5. Fix every `anchor_missing`, `fact_changed`, and `fact_lost` by editing only the affected
   sentence, then re-run. Stop after 2 fix rounds and report what remains.

A `fact_without_anchor` warning means only your verdict covers that fact; judge it carefully.
`no_verdicts` means the meaning-level check has not been done yet.

## Independent pass (optional)

Your own verdicts are still self-grading. When the harness can start a subagent, give it only
the rewrite and `facts.json` (not the original) and ask for a verdict per fact, then compare
with yours and recheck any disagreement.
