"""Shared glossary for long documents (story 003).

``extract`` lists recurring acronyms, proper-name sequences, and katakana terms plus any terms
the user names. The LLM then settles each entry (``keep`` or ``rewrite-consistently`` with a
``rendering``), and ``verify`` checks a rewrite against those decisions.
"""

import re

from .protect import PLACEHOLDER_RE
from .text import term_pattern

KEEP, CONSISTENT = "keep", "rewrite-consistently"
DECISIONS = (KEEP, CONSISTENT)
MIN_COUNT = 2

_TOKEN = re.compile(r"[^\W\d_][\w'’-]*")
_CJK = re.compile(r"[぀-ヿ一-鿿]")
_KATAKANA = re.compile(r"[゠-ヿ]{3,}")
_BREAKS = set(".!?\n。！？")


class GlossaryError(ValueError):
    """Raised when a glossary file is malformed."""


def _count(term, text):
    """Occurrences of ``term`` in ``text`` as a whole word or phrase."""
    return len(term_pattern(term, word_bounded=not _CJK.search(term)).findall(text))


def _scan(text):
    """Yield ``(kind, term)`` for acronyms and capitalised name sequences, in order."""
    run, prev_end, at_start = [], 0, True

    def emit():
        """Close the current capitalised run."""
        nonlocal run
        single = len(run) == 1
        if run and not (single and (run[0][1] or len(run[0][0]) < 3)):
            yield "name", " ".join(w for w, _ in run)
        run = []

    for m in _TOKEN.finditer(text):
        gap = text[prev_end:m.start()]
        word = m.group(0)
        if run and gap != " ":
            yield from emit()
        if any(c in _BREAKS for c in gap):
            at_start = True
        elif gap.strip():
            at_start = False
        if len(word) >= 2 and word.isupper():
            yield from emit()
            yield "acronym", word
        elif word[0].isupper():
            run.append((word, at_start and not run))
        else:
            yield from emit()
        at_start = False
        prev_end = m.end()
    yield from emit()


def extract(text, keep=(), terms=(), min_count=MIN_COUNT):
    """Return glossary entries for recurring terms, most frequent first."""
    text = PLACEHOLDER_RE.sub(" ", text)
    found = {}
    for kind, term in _scan(text):
        found.setdefault(term, kind)
    for term in _KATAKANA.findall(text):
        found.setdefault(term, "katakana")
    for term in terms:
        found[term] = "term"
    for term in keep:
        found[term] = "keep"

    entries = []
    for term, kind in found.items():
        count = _count(term, text)
        if count >= min_count or kind in ("term", "keep"):
            decision = KEEP if kind in ("acronym", "name", "keep") else CONSISTENT
            entries.append({"term": term, "kind": kind, "count": count,
                            "decision": decision, "rendering": None})
    entries.sort(key=lambda e: (-e["count"], e["term"]))
    return entries


def parse(data):
    """Validate a glossary list loaded from JSON and return it."""
    if not isinstance(data, list):
        raise GlossaryError("glossary must be a JSON list of entries")
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or not isinstance(entry.get("term"), str) or not entry["term"]:
            raise GlossaryError(f"entry {i}: 'term' must be a non-empty string")
        if entry.get("decision") not in DECISIONS:
            raise GlossaryError(f"entry {i} ({entry['term']}): 'decision' must be one of {', '.join(DECISIONS)}")
        rendering = entry.get("rendering")
        if rendering is not None and not isinstance(rendering, str):
            raise GlossaryError(f"entry {i} ({entry['term']}): 'rendering' must be a string or null")
    return data


def verify(original, rewritten, entries):
    """Check a rewrite against glossary decisions; return a report with warnings."""
    original = PLACEHOLDER_RE.sub(" ", original)
    rewritten = PLACEHOLDER_RE.sub(" ", rewritten)
    warnings = []
    for entry in entries:
        term, rendering = entry["term"], entry.get("rendering")
        before, after = _count(term, original), _count(term, rewritten)
        if entry["decision"] == KEEP:
            if after < before:
                warnings.append({"type": "term_lost", "term": term, "original": before, "rewritten": after})
            continue
        if not rendering:
            warnings.append({"type": "rendering_missing", "term": term})
        elif rendering != term:
            if after:
                warnings.append({"type": "term_leftover", "term": term, "rendering": rendering, "count": after})
            if before and not _count(rendering, rewritten):
                warnings.append({"type": "rendering_unused", "term": term, "rendering": rendering})
    return {"ok": not warnings, "warnings": warnings}
