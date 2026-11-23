---
trigger: model_decision
description: Paraphrase, rewrite, reword, or produce variants of text or a .txt/.md file while keeping numbers, names, code, and links intact. Use for requests like "paraphrase this", "rewrite in a formal tone", "viết lại", "言い換え".
---

# Paraphrase workflow

The skill lives in `.paraphrase-anything/`. Read `.paraphrase-anything/SKILL.md` and follow it; it is
the single source for the workflow, modes, and checks. Do not rely on a remembered copy.

In short: pin the original verbatim, rewrite it, then verify the rewrite against the original
with the bundled tool instead of judging by eye:

```bash
python .paraphrase-anything/scripts/pe.py check original.txt rewrite.txt
```

Use `python3` if `python` is not Python 3. Fix every reported error before answering.
