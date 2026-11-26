"""JSON locale files: every string value is a segment; keys and structure never change (story 031).

Rebuild replaces only the bytes of each rewritten string literal (re-escaped), so indentation,
key order, and the trailing newline survive. ``keys`` limits the rewritten values to dotted key
paths matching any of the given globs (``menu.*``, ``errors.*.title``).
"""

import fnmatch
import json

from .base import FormatError, number, worth_rewriting


def _validate(source):
    """Raise ``FormatError`` unless ``source`` is a JSON object or array."""
    try:
        data = json.loads(source.lstrip("﻿"))
    except json.JSONDecodeError as e:
        raise FormatError(f"not valid JSON: {e}") from None
    if not isinstance(data, (dict, list)):
        raise FormatError("a JSON locale file must be an object or an array of strings")


def _literal_end(source, i):
    """Offset just past the string literal that opens at ``i``."""
    j = i + 1
    while source[j] != '"':
        j += 2 if source[j] == "\\" else 1
    return j + 1


def _values(source):
    """Yield ``(start, end, path)`` for every string value literal (keys excluded)."""
    stack, i, n = [], 0, len(source)
    while i < n:
        c = source[i]
        if c == '"':
            end = _literal_end(source, i)
            top = stack[-1] if stack else None
            if top and top["kind"] == "obj" and top["expect_key"]:
                top["key"] = json.loads(source[i:end])
            else:
                yield i, end, ".".join(str(f["key"] if f["kind"] == "obj" else f["index"]) for f in stack)
            i = end
            continue
        if c == "{":
            stack.append({"kind": "obj", "expect_key": True, "key": None})
        elif c == "[":
            stack.append({"kind": "arr", "index": 0})
        elif c in "}]":
            stack.pop()
        elif c == ":":
            stack[-1]["expect_key"] = False
        elif c == ",":
            if stack[-1]["kind"] == "obj":
                stack[-1]["expect_key"] = True
            else:
                stack[-1]["index"] += 1
        i += 1


def _scan(source, keys=None):
    """``(segments, skipped)`` of ``source``: values worth rewriting, and the ones left alone."""
    _validate(source)
    segments, skipped = [], []
    for start, end, path in _values(source):
        text = json.loads(source[start:end])
        if keys and not any(fnmatch.fnmatchcase(path, g) for g in keys):
            continue
        why = worth_rewriting(text)
        if why:
            skipped.append({"context": path, "text": text, "why": why})
        else:
            segments.append({"start": start, "end": end, "text": text, "context": path})
    return number(segments), skipped


def extract(source, keys=None):
    """Return one segment per string value (``context`` is its dotted key path)."""
    return _scan(source, keys)[0]


def skipped(source, keys=None):
    """String values that are not rewritten (empty, a single short word, or only placeholders)."""
    return _scan(source, keys)[1]


def _encode(text, original):
    """``text`` as a JSON string literal, escaping non-ASCII only when ``original`` did."""
    ascii_only = original.isascii() and "\\u" in original
    return json.dumps(text, ensure_ascii=ascii_only)


def rebuild(source, rewritten, keys=None):
    """Replace the rewritten string literals; every other byte is kept."""
    segments = extract(source, keys)
    known = {s["id"] for s in segments}
    unknown = sorted(set(rewritten) - known)
    if unknown:
        raise FormatError(f"unknown segment id(s): {', '.join(map(str, unknown))}")
    out, pos = [], 0
    for seg in segments:
        new = rewritten.get(seg["id"])
        if new is None or new == seg["text"]:
            continue
        if not new.strip():
            raise FormatError(f"segment {seg['id']} is empty")
        out += [source[pos:seg["start"]], _encode(new.replace("\r\n", "\n"), source[seg["start"]:seg["end"]])]
        pos = seg["end"]
    out.append(source[pos:])
    return "".join(out)


SPECS = [{"name": "json", "extensions": [".json"], "output": ".json",
          "options": {"keys": {"type": "list", "help": "dotted key-path globs to rewrite, e.g. menu.*,errors.*"}}}]
