---
description: Paraphrase workflow for rewriting text files
applyTo: "**/*.txt,**/*.md"
---

# Paraphrase workflow

When the user asks to paraphrase, rewrite, reword, or produce variants of text (including
"viết lại" or "言い換え"), read `.paraphrase-anything/SKILL.md` and follow it. It is the single
source for the workflow, modes, and checks.

Verify the rewrite against the original with the bundled tool instead of judging by eye:

```bash
python .paraphrase-anything/scripts/pe.py check original.txt rewrite.txt
```

Use `python3` if `python` is not Python 3. Fix every reported error before answering.
For any other request, ignore this file.
