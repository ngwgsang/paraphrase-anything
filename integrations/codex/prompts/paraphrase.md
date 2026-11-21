---
description: Paraphrase, rewrite, or produce variants of text or a file
---

# /paraphrase

Rewrite text in a chosen style while keeping facts, numbers, code, and links intact.

## Usage

`/paraphrase [mode] <text or file>`

- **mode** (optional): `standard` (default), `light`, `creative`, `shorten`, `expand`.
- **text or file**: Text to rewrite or path to a `.txt` or `.md` file.

## Workflow

1. Save the original text as canonical.
2. Resolve mode, language, and length target.
3. If code or formatting is present, mask opaque spans first:
   ```bash
   pe protect input.txt -o masked.txt --map map.json
   ```
4. Rewrite the content in the target style.
5. If spans were protected, restore them:
   ```bash
   pe restore masked-rewrite.txt --map map.json -o rewrite.txt
   ```
6. Verify factual fidelity:
   ```bash
   pe check original.txt rewrite.txt
   ```
7. Check advisory divergence:
   ```bash
   pe metrics original.txt rewrite.txt --mode standard
   ```
8. Return the rewritten text and a one-line summary of verification results.
