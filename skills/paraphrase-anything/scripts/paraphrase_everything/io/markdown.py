"""Markdown: prose blocks only.

Segments are headings (text after the ``#`` marker), list items, block-quote paragraphs, and
plain paragraphs. Front matter, fenced and indented code, tables, HTML blocks, rules, and link
or footnote definitions are never segments. Inline code and URLs inside prose are handled by
``protect`` before rewriting.
"""

import re

from .base import make_segment, number, rebuild as _rebuild, split_lines

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_QUOTE = re.compile(r"^\s{0,3}(?:>[ \t]?)+")
_HEADING = re.compile(r"^(\s{0,3}#{1,6}[ \t]+)(.*?)([ \t]+#+[ \t]*)?$")
_RULE = re.compile(r"^\s{0,3}(?:([-*_])(?:[ \t]*\1){2,}|=+)[ \t]*$")
_ITEM = re.compile(r"^([ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+(?:\[[ xX]\][ \t]+)?)(?=\S)")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_HTML = re.compile(r"^\s{0,3}</?[A-Za-z!]")
_DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S")
_INDENTED_CODE = re.compile(r"^(?:\t| {4})")
_LEADING_WS = re.compile(r"[ \t]*")


def _front_matter_end(source, lines):
    """Index of the first line after YAML/TOML front matter, or 0 when there is none."""
    if not lines:
        return 0
    marker = source[lines[0][0]:lines[0][1]].rstrip()
    if marker not in ("---", "+++"):
        return 0
    closers = {marker, "..."} if marker == "---" else {marker}
    for i in range(1, len(lines)):
        if source[lines[i][0]:lines[i][1]].rstrip() in closers:
            return i + 1
    return 0


def _table_lines(bodies):
    """Flags marking table rows: a header row followed by a separator row, then rows with pipes."""
    flags = [False] * len(bodies)
    for i, body in enumerate(bodies):
        if body.lstrip().startswith("|"):
            flags[i] = True
        if "|" in body and i + 1 < len(bodies) and "|" in bodies[i + 1] \
                and _TABLE_SEP.match(bodies[i + 1]):
            j = i
            while j < len(bodies) and bodies[j].strip() and "|" in bodies[j]:
                flags[j] = True
                j += 1
    return flags


def extract(source):
    """Return prose segments of a Markdown document in order."""
    lines = split_lines(source)
    spans = [(s, e, _QUOTE.match(source[s:e])) for s, e, _ in lines]
    prefixes = [m.group(0) if m else "" for _, _, m in spans]
    bodies = [source[s + len(p):e] for (s, e, _), p in zip(spans, prefixes)]
    tables = _table_lines(bodies)

    segments, group = [], None
    fence, in_html, in_list = None, False, False

    def flush():
        """Close the group being collected."""
        nonlocal group
        if group:
            segments.append(make_segment(source, group["parts"], group["cont"] or ""))
        group = None

    for i in range(_front_matter_end(source, lines), len(lines)):
        start, end = lines[i][0], lines[i][1]
        prefix, body = prefixes[i], bodies[i]
        base = start + len(prefix)
        if fence:
            closing = re.match(r"^\s{0,3}(" + re.escape(fence[0]) + r"{%d,})\s*$" % fence[1], body)
            if closing:
                fence = None
            continue
        opening = _FENCE.match(body)
        if opening:
            flush()
            fence = (opening.group(1)[0], len(opening.group(1)))
            continue
        if not body.strip():
            flush()
            in_html = False
            continue
        if in_html:
            continue
        if _HTML.match(body):
            flush()
            in_html = True
            continue
        if tables[i] or _DEFINITION.match(body) or _RULE.match(body):
            flush()
            in_list = False
            continue
        heading = _HEADING.match(body)
        if heading:
            flush()
            in_list = False
            text = heading.group(2).rstrip()
            if text:
                at = base + len(heading.group(1))
                segments.append(make_segment(source, [(at, at + len(text))]))
            continue
        item = _ITEM.match(body)
        if item:
            flush()
            in_list = True
            group = {"parts": [(base + len(item.group(1)), end)], "cont": None, "prefix": prefix}
            continue
        if group and group["prefix"] == prefix:
            if group["cont"] is None:
                group["cont"] = prefix + _LEADING_WS.match(body).group(0)
            cont = group["cont"]
            at = start + len(cont) if source.startswith(cont, start) else base
            group["parts"].append((at, end))
            continue
        flush()
        if not in_list and not prefix and _INDENTED_CODE.match(body):
            continue
        if not _INDENTED_CODE.match(body):
            in_list = False
        indent = len(_LEADING_WS.match(body).group(0))
        group = {"parts": [(base + indent, end)], "cont": None, "prefix": prefix}
    flush()
    return number(segments)


def rebuild(source, rewritten):
    """Rebuild ``source`` with rewritten prose texts (``{id: text}``)."""
    return _rebuild(source, extract(source), rewritten)
