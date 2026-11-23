---
mode: agent
description: Paraphrase, rewrite, or produce variants of text or a file
tools: ['codebase', 'editFiles', 'runCommands']
---

# /paraphrase

Rewrite text in a chosen style while keeping facts, numbers, code, and links intact.

Request: ${input:request:[mode] <text or file>, e.g. "creative notes.md"}

- **mode** (optional): `standard` (default), `light`, `creative`, `shorten`, `expand`.
- **text or file**: text to rewrite or the path to a `.txt` or `.md` file.

Read and follow `.paraphrase-anything/SKILL.md`; it is the single source for the workflow,
modes, and verification steps. Run the tooling with
`python .paraphrase-anything/scripts/pe.py <command>` (use `python3` if `python` is not Python 3).
Run `pe check` on the rewrite in the terminal and fix every reported error before you answer.
