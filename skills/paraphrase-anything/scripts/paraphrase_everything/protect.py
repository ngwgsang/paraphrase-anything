"""Mask opaque spans before rewriting and restore them afterwards (story 001).

Only spans the LLM does not need to understand are masked: code, URLs, emails,
LaTeX, HTML tags, and user-supplied terms. Numbers, names, and citations stay
readable and are verified by ``check`` instead.
"""

import re

from .text import term_pattern

PLACEHOLDER = "⟦P{}⟧"
# Tolerate whitespace an LLM may insert inside the brackets.
PLACEHOLDER_RE = re.compile(r"⟦\s*P\s*(\d+)\s*⟧")

# Ordered by priority: earlier detectors win when spans overlap.
DETECTORS = [
    ("code_block", re.compile(
        r"^[ \t]*(?P<fence>`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*(?P=fence)[ \t]*$|\Z)",
        re.MULTILINE | re.DOTALL)),
    ("inline_code", re.compile(r"(?P<ticks>`+)(?!`).+?(?<!`)(?P=ticks)(?!`)")),
    ("latex_block", re.compile(r"\$\$.+?\$\$|\\\[.+?\\\]", re.DOTALL)),
    # Pandoc rule: no space after the opening $, none before the closing $,
    # and no digit right after it, so "$5 and $10" is not math.
    ("latex_inline", re.compile(r"(?<![\\$])\$(?=\S)[^$\n]*?(?<=\S)\$(?!\d)|\\\(.+?\\\)")),
    ("html_comment", re.compile(r"<!--.*?-->", re.DOTALL)),
    ("html_tag", re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")),
    ("link_target", re.compile(r"(?<=\]\()(?:<[^>\n]*>|[^)\s]+)(?:\s+\"[^\"\n]*\")?(?=\))")),
    # ASCII-only bodies so a URL glued to CJK text ("…を参照") stops at the URL.
    ("url", re.compile(r"(?<![A-Za-z0-9])(?:https?://|www\.)[A-Za-z0-9\-._~:/?#@!$&*+,;=%]+")),
    ("email", re.compile(r"(?<![A-Za-z0-9.+-])[A-Za-z0-9.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
]

_TRAILING_PUNCT = ".,;:!?"


class ProtectError(ValueError):
    """Raised when input cannot be protected safely."""


def find_spans(text, keep=()):
    """Return sorted, non-overlapping ``(start, end, type)`` opaque spans."""
    detectors = list(DETECTORS)
    # Longer terms first so "New York City" beats "New York".
    for term in sorted({t for t in keep if t}, key=len, reverse=True):
        detectors.append(("keep", term_pattern(term)))

    taken = []  # (start, end, type)
    for kind, pattern in detectors:
        for m in pattern.finditer(text):
            start, end = m.span()
            if kind == "url":
                while end > start and text[end - 1] in _TRAILING_PUNCT:
                    end -= 1
            if start == end:
                continue
            if any(start < e and s < end for s, e, _ in taken):
                continue
            taken.append((start, end, kind))
    return sorted(taken)


def protect(text, keep=()):
    """Return ``(masked_text, mapping)``.

    ``mapping`` is JSON-serialisable: ``{"version": 1, "placeholders": {"P1": {...}}}``.
    """
    if PLACEHOLDER_RE.search(text):
        raise ProtectError("input already contains placeholder-like text (⟦P<n>⟧)")

    parts, placeholders, pos = [], {}, 0
    for n, (start, end, kind) in enumerate(find_spans(text, keep), 1):
        key = f"P{n}"
        placeholders[key] = {"type": kind, "text": text[start:end]}
        parts.append(text[pos:start])
        parts.append(PLACEHOLDER.format(n))
        pos = end
    parts.append(text[pos:])
    return "".join(parts), {"version": 1, "placeholders": placeholders}


def restore(text, mapping):
    """Return ``(restored_text, report)``.

    Every placeholder must appear exactly once. Missing, duplicated, and unknown
    placeholders are reported; known ones are restored wherever they appear and
    unknown ones are left untouched.
    """
    placeholders = mapping.get("placeholders", {})
    seen = {}

    def replace(m):
        """Swap one placeholder for its original text and count the occurrence."""
        key = f"P{int(m.group(1))}"
        seen[key] = seen.get(key, 0) + 1
        entry = placeholders.get(key)
        return entry["text"] if entry else m.group(0)

    restored = PLACEHOLDER_RE.sub(replace, text)

    issues = []
    for key, entry in placeholders.items():
        count = seen.get(key, 0)
        if count == 0:
            issues.append({"type": "placeholder_missing", "id": key,
                           "span_type": entry["type"], "text": entry["text"]})
        elif count > 1:
            issues.append({"type": "placeholder_duplicated", "id": key, "count": count})
    for key in seen:
        if key not in placeholders:
            issues.append({"type": "placeholder_unknown", "id": key})

    return restored, {"ok": not issues, "restored": len(seen.keys() & placeholders.keys()),
                      "total": len(placeholders), "issues": issues}
