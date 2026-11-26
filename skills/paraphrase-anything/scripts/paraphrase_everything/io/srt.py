"""SubRip (.srt) and WebVTT (.vtt): only cue text changes.

Indices, timing lines, headers, and NOTE/STYLE/REGION blocks are never segments, so timing
cannot change. ``lint`` reports advisory line-length and reading-speed warnings.
"""

import re

from .base import FormatError, make_segment, number, rebuild as _rebuild, split_lines

_VTT = re.compile(r"^﻿?WEBVTT")
TIMING = re.compile(
    r"^\s*(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{3})")


def _seconds(hours, minutes, seconds, millis):
    """Convert timestamp groups (hours may be ``None``) to seconds."""
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _cue_blocks(source):
    """Yield lists of ``(start, end)`` line spans for each blank-line separated block."""
    block = []
    for start, end, _ in split_lines(source):
        if source[start:end].strip():
            block.append((start, end))
        elif block:
            yield block
            block = []
    if block:
        yield block


def extract(source):
    """Return one segment per cue text, with the cue's ``duration`` in seconds."""
    segments = []
    for block in _cue_blocks(source):
        for k, (start, end) in enumerate(block[:2]):
            m = TIMING.match(source[start:end])
            if m:
                break
        else:
            continue
        text_lines = block[k + 1:]
        if text_lines:
            g = m.groups()
            duration = _seconds(*g[4:]) - _seconds(*g[:4])
            segments.append(make_segment(source, text_lines, duration=duration))
    return number(segments)


def sniff_vtt(source):
    """Whether ``source`` starts with a WebVTT header."""
    return bool(_VTT.match(source))


def sniff_srt(source):
    """Whether ``source`` has at least one cue with a timing line."""
    return bool(extract(source))


SPECS = [{"name": "vtt", "extensions": [".vtt"], "output": ".vtt", "sniff": sniff_vtt, "priority": 30},
         {"name": "srt", "extensions": [".srt"], "output": ".srt", "sniff": sniff_srt, "priority": 20}]


def rebuild(source, rewritten):
    """Rebuild ``source`` with new cue texts; reject text that would break the cue structure."""
    for seg_id, text in rewritten.items():
        if re.search(r"\n\s*\n", text.replace("\r", "")):
            raise FormatError(f"segment {seg_id}: a blank line would split the cue")
        if any(TIMING.match(line) for line in text.splitlines()):
            raise FormatError(f"segment {seg_id}: text looks like a timing line")
    return _rebuild(source, extract(source), rewritten)


def lint(source, limits):
    """Advisory warnings for cue text: lines over ``max_line_chars``, speed over ``max_cps``."""
    warnings = []
    for seg in extract(source):
        for n, line in enumerate(seg["text"].split("\n"), 1):
            if limits["max_line_chars"] and len(line) > limits["max_line_chars"]:
                warnings.append({"type": "line_too_long", "cue": seg["id"], "line": n,
                                 "chars": len(line), "max": limits["max_line_chars"]})
        chars = len(seg["text"].replace("\n", ""))
        if limits["max_cps"] and seg["duration"] > 0 and chars / seg["duration"] > limits["max_cps"]:
            warnings.append({"type": "reading_speed", "cue": seg["id"],
                             "cps": round(chars / seg["duration"], 1), "max": limits["max_cps"]})
    return warnings
