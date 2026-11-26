"""gettext PO / POT catalogs: translations are segments; ids, context, and comments never change (story 031).

In a catalog with translations, each non-empty ``msgstr`` (and each ``msgstr[n]`` plural form) is a
segment. In a template, where every ``msgstr`` is empty, ``msgid`` and ``msgid_plural`` are the
segments instead. The header entry (``msgid ""``) is never rewritten. A field written over several
``"..."`` lines is joined for rewriting and written back over several lines, one per ``\\n``.
"""

import re

from .base import FormatError, line_ending, number, split_lines, worth_rewriting

_FIELD = re.compile(r'^[ \t]*(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)[ \t]+(?=")')
_CONT = re.compile(r'^[ \t]*(?=")')
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
_ENCODE = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def _decode(literal):
    """The text of a PO string literal (with its quotes)."""
    body, out, i = literal[1:-1], [], 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def _encode(text):
    """``text`` as the body of a PO string literal (without quotes)."""
    return "".join(_ENCODE.get(ch, ch) for ch in text)


def _literal_span(source, start, end):
    """``(start, end)`` of the quoted literal on the line ``source[start:end]``, or ``None``."""
    line = source[start:end].rstrip()
    q = line.find('"')
    if q < 0 or not line.endswith('"') or len(line) - q < 2:
        return None
    return start + q, start + len(line)


def _entries(source):
    """Parse ``source`` into entries: ``{field: {"spans": [...], "text": str}}`` in order."""
    entries, entry, field = [], {}, None
    for start, end, _ in split_lines(source):
        line = source[start:end]
        m = _FIELD.match(line)
        if m:
            name = m.group(1)
            if name in ("msgctxt", "msgid") and any(k.startswith("msgstr") for k in entry):
                entries.append(entry)
                entry = {}
            span = _literal_span(source, start + m.end(), end)
            if span is None:
                raise FormatError(f"malformed PO line: {line.strip()}")
            field = name
            entry[field] = {"spans": [span]}
        elif _CONT.match(line) and field and line.strip():
            span = _literal_span(source, start, end)
            if span is None:
                raise FormatError(f"malformed PO line: {line.strip()}")
            entry[field]["spans"].append(span)
        elif not line.strip() or line.lstrip().startswith("#"):
            field = None
            if not line.strip() and entry:
                entries.append(entry)
                entry = {}
        else:
            raise FormatError(f"malformed PO line: {line.strip()}")
    if entry:
        entries.append(entry)
    for e in entries:
        for value in e.values():
            value["text"] = "".join(_decode(source[s:t]) for s, t in value["spans"])
    return [e for e in entries if "msgid" in e]


def _scan(source):
    """``(segments, skipped)``: rewritable fields, and the ones left alone."""
    entries = [e for e in _entries(source) if e["msgid"]["text"]]  # drop the header
    template = all(not v["text"] for e in entries for k, v in e.items() if k.startswith("msgstr"))
    segments, skipped = [], []
    for e in entries:
        fields = ("msgid", "msgid_plural") if template else sorted(k for k in e if k.startswith("msgstr"))
        for name in fields:
            if name not in e or not e[name]["text"]:
                continue
            value = e[name]
            context = e["msgid"]["text"] if name.startswith("msgstr") else name
            why = worth_rewriting(value["text"])
            if why:
                skipped.append({"context": context, "text": value["text"], "why": why})
                continue
            segments.append({"start": value["spans"][0][0], "end": value["spans"][-1][1], "text": value["text"],
                             "context": context, "lines": len(value["spans"])})
    return number(segments), skipped


def extract(source):
    """Return one segment per translation (or per source string in a template)."""
    return _scan(source)[0]


def skipped(source):
    """Fields that are not rewritten (empty, a single short word, or only placeholders)."""
    return _scan(source)[1]


def _field_text(text, seg, source, eol):
    """The rewritten literal(s) for ``seg``: one line, or ``""`` plus one line per ``\\n``."""
    if seg["lines"] == 1:
        return f'"{_encode(text)}"'
    line_start = source.rfind("\n", 0, seg["start"]) + 1
    indent = source[line_start:seg["start"]] if not source[line_start:seg["start"]].strip() else ""
    chunks = re.findall(r"[^\n]*\n|[^\n]+$", text)
    return f'""{eol}' + eol.join(f'{indent}"{_encode(c)}"' for c in chunks)


def rebuild(source, rewritten):
    """Replace the rewritten fields; ids, context, comments, and flags are kept byte for byte."""
    segments = extract(source)
    unknown = sorted(set(rewritten) - {s["id"] for s in segments})
    if unknown:
        raise FormatError(f"unknown segment id(s): {', '.join(map(str, unknown))}")
    eol = line_ending(source)
    out, pos = [], 0
    for seg in segments:
        new = rewritten.get(seg["id"])
        if new is None or new == seg["text"]:
            continue
        new = new.replace("\r\n", "\n")
        if not new.strip():
            raise FormatError(f"segment {seg['id']} is empty")
        out += [source[pos:seg["start"]], _field_text(new, seg, source, eol)]
        pos = seg["end"]
    out.append(source[pos:])
    return "".join(out)


SPECS = [{"name": "po", "extensions": [".po", ".pot"], "output": ".po"}]
