"""Format-preserving I/O (story 006).

Each format module exposes ``extract(source) -> segments`` and ``rebuild(source, rewritten)``.
Add a format by adding a module and one entry to ``FORMATS``.
"""

import re
from pathlib import Path

from . import markdown, srt, text
from .base import FormatError, public

FORMATS = {"text": text, "markdown": markdown, "srt": srt, "vtt": srt}
EXTENSIONS = {".txt": "text", ".md": "markdown", ".markdown": "markdown",
              ".srt": "srt", ".vtt": "vtt"}

_VTT = re.compile(r"^﻿?WEBVTT")
_MARKDOWN = re.compile(
    r"^(?:#{1,6}[ \t]+\S|[ \t]*(?:[-*+]|\d+[.)])[ \t]+\S|[ \t]{0,3}(?:```|~~~)|[ \t]{0,3}>)"
    r"|\]\(|\*\*\S|^\|.*\|[ \t]*$", re.MULTILINE)


def detect(source, path=None):
    """Pick a format from the file extension, else from the content."""
    if path:
        fmt = EXTENSIONS.get(Path(path).suffix.lower())
        if fmt:
            return fmt
    if _VTT.match(source):
        return "vtt"
    if srt.extract(source):
        return "srt"
    return "markdown" if _MARKDOWN.search(source) else "text"


def _module(fmt):
    """Return the module for ``fmt`` or raise ``FormatError``."""
    try:
        return FORMATS[fmt]
    except KeyError:
        raise FormatError(f"unknown format: {fmt} (choose from {', '.join(sorted(FORMATS))})") from None


def extract(source, fmt):
    """Return the segments of ``source`` in format ``fmt``."""
    return _module(fmt).extract(source)


def rebuild(source, fmt, rewritten):
    """Return ``source`` with segments replaced by ``rewritten`` (``{id: text}``)."""
    return _module(fmt).rebuild(source, rewritten)


__all__ = ["FORMATS", "FormatError", "detect", "extract", "public", "rebuild"]
