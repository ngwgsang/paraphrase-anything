"""Plain text: one segment per paragraph (blank-line separated)."""

from .base import make_segment, number, rebuild as _rebuild, split_lines

SPECS = [{"name": "text", "extensions": [".txt"], "output": ".txt", "fallback": True}]


def extract(source):
    """Return one segment per paragraph; indentation and inner line breaks stay in the source."""
    segments, parts = [], []

    def flush():
        """Close the paragraph being collected."""
        nonlocal parts
        if parts:
            segments.append(make_segment(source, parts))
        parts = []

    for start, end, _ in split_lines(source):
        line = source[start:end]
        if not line.strip():
            flush()
            continue
        if not parts:
            start += len(line) - len(line.lstrip())
        parts.append((start, end))
    flush()
    return number(segments)


def rebuild(source, rewritten):
    """Rebuild ``source`` with rewritten paragraph texts (``{id: text}``)."""
    return _rebuild(source, extract(source), rewritten)
