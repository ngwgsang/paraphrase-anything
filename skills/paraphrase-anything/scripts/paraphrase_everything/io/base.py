"""Shared helpers for format modules: line spans, segments, and rebuilding (story 006).

A segment is a dict with ``id``, ``text`` (LF-normalised), the source span ``start``/``end``,
and ``cont_prefix``: the text that opens every line after the first (quote marker, indent).
Everything outside the spans is copied from the source untouched.
"""

import re

_LINE = re.compile(r"([^\r\n]*)(\r\n|\n|\r|$)")


class FormatError(ValueError):
    """Raised when a segment list cannot be applied to its source."""


def split_lines(source):
    """Return ``[(start, content_end, next_start), ...]`` for every line of ``source``."""
    lines, pos = [], 0
    while pos < len(source):
        m = _LINE.match(source, pos)
        lines.append((pos, m.end(1), m.end()))
        pos = m.end()
    return lines


def line_ending(source):
    """The dominant line ending of ``source``: ``"\\r\\n"`` or ``"\\n"``."""
    crlf = source.count("\r\n")
    return "\r\n" if crlf > source.count("\n") - crlf else "\n"


def make_segment(source, parts, cont_prefix="", **extra):
    """Build a segment from per-line ``(start, end)`` content spans; the last line is right-trimmed."""
    parts = list(parts)
    start, end = parts[-1]
    parts[-1] = (start, start + len(source[start:end].rstrip()))
    text = "\n".join(source[s:e] for s, e in parts)
    return dict(extra, start=parts[0][0], end=parts[-1][1], text=text, cont_prefix=cont_prefix)


def number(segments):
    """Give segments 1-based ids in document order and return them."""
    for i, seg in enumerate(segments, 1):
        seg["id"] = i
    return segments


def rebuild(source, segments, rewritten):
    """Replace segment spans with the texts in ``rewritten`` (``{id: text}``); keep the rest."""
    known = {seg["id"] for seg in segments}
    unknown = sorted(set(rewritten) - known)
    if unknown:
        raise FormatError(f"unknown segment id(s): {', '.join(map(str, unknown))}")
    eol = line_ending(source)
    out, pos = [], 0
    for seg in segments:
        new = rewritten.get(seg["id"])
        if new is None or new == seg["text"]:
            continue
        new = new.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not new:
            raise FormatError(f"segment {seg['id']} is empty")
        out.append(source[pos:seg["start"]])
        out.append((eol + seg["cont_prefix"]).join(new.split("\n")))
        pos = seg["end"]
    out.append(source[pos:])
    return "".join(out)


def public(segments):
    """The JSON-facing view of segments: ``id``, ``text``, and ``context`` when the format gives one."""
    return [dict({"id": s["id"], "text": s["text"]}, **({"context": s["context"]} if "context" in s else {}))
            for s in segments]


SHORT_WORD = 10
_WORD_RUN = re.compile(r"\w+")


def worth_rewriting(text):
    """``None`` when ``text`` has prose to rewrite, else why it is left alone.

    Used by string-table formats (locale files, CSV cells) where many values are labels.
    """
    from ..protect import find_spans  # imported here: protect is not needed by the other formats

    chars = list(text)
    for s, e, _ in find_spans(text):
        chars[s:e] = " " * (e - s)
    prose = "".join(chars).strip()
    if not prose:
        return "empty" if not text.strip() else "only placeholders or markup"
    if not _WORD_RUN.search(prose):
        return "no words"
    if not any(ch.isspace() for ch in prose) and len(prose) <= SHORT_WORD:
        return "a single short word"
    return None
