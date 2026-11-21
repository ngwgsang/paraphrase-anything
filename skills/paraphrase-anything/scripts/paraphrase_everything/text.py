"""Language-agnostic text helpers. Language specifics come from ``lang`` data."""

import re
import unicodedata

# Full-width terminators end a sentence immediately; ASCII ones need whitespace after.
_CLOSERS = "\"'”’)]）」』】"


def normalize(text):
    """NFKC: folds full-width digits and punctuation, composes accents."""
    return unicodedata.normalize("NFKC", text)


def term_pattern(term, word_bounded=True, flags=0):
    """Regex for ``term``; word boundaries apply only on sides that are word chars."""
    escaped = re.escape(term)
    if not word_bounded:
        return re.compile(escaped, flags)
    start = r"(?<!\w)" if re.match(r"\w", term[:1]) else ""
    end = r"(?!\w)" if re.match(r"\w", term[-1:]) else ""
    return re.compile(start + escaped + end, flags)


def markers_pattern(markers, word_bounded):
    """One alternation, longest first, so "không hề" counts once, not twice.

    A leading or trailing ``*`` in a marker drops the word boundary on that side
    (e.g. ``*n't`` matches inside "don't"). Straight and curly apostrophes match each other.
    """
    if not markers:
        return None
    parts = []
    for m in sorted(set(markers), key=lambda x: len(x.strip("*")), reverse=True):
        core = m.strip("*")
        body = re.escape(core).replace("'", "['’]")
        if word_bounded:
            if not m.startswith("*") and re.match(r"\w", core[:1]):
                body = r"(?<!\w)" + body
            if not m.endswith("*") and re.match(r"\w", core[-1:]):
                body += r"(?!\w)"
        parts.append(body)
    return re.compile("|".join(parts), re.IGNORECASE)


def count(pattern, text):
    return len(pattern.findall(text)) if pattern else 0


def split_sentences(text, data):
    """Split into ``[(start, end), ...]`` spans, skipping empty ones.

    Newlines always end a sentence (headings, list items, paragraphs).
    """
    terminators = set(data["sentence_terminators"])
    abbreviations = set(data["abbreviations"])
    spans, start, i, n = [], 0, 0, len(text)

    def push(end):
        nonlocal start
        if text[start:end].strip():
            s = start + len(text[start:end]) - len(text[start:end].lstrip())
            e = start + len(text[start:end].rstrip())
            spans.append((s, e))
        start = end

    while i < n:
        ch = text[i]
        if ch == "\n":
            push(i)
            i += 1
            continue
        if ch in terminators:
            j = i + 1
            while j < n and (text[j] in terminators or text[j] in _CLOSERS):
                j += 1
            if ord(ch) > 0x7F:  # full-width: split right away
                push(j)
                i = j
                continue
            if j >= n or text[j].isspace():
                k = i
                while k > start and not text[k - 1].isspace():
                    k -= 1
                token = text[k:i + 1]
                is_initial = len(token) == 2 and token[0].isupper()
                if token not in abbreviations and not is_initial:
                    push(j)
                    i = j
                    continue
            i = j
            continue
        i += 1
    push(n)
    return spans
