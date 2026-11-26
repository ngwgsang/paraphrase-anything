"""Files, Long, and Variants routes inside a harness session (story 027).

Pure helpers the harness calls: turning a file in any registered format into session prose
and back, splitting the masked text into chunks with their sentence ranges, and validating a
multi-variant plan. They hold no session state.
"""

import re

from . import chunk, glossary, io, lang
from .check import Doc

TEXT_FORMAT = io.REGISTRY.fallback
FILE_EXTENSIONS = {name: ext for name, ext in io.OUTPUTS.items() if name != TEXT_FORMAT}
SEGMENT_BREAK = "\n\n"
MAX_VARIANTS = 5
_BLOCK_BREAK = re.compile(r"(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)")


class RouteError(Exception):
    """The input cannot be used by this route."""


# --- Files ------------------------------------------------------------------------------------

def file_prose(source, fmt, opts=None):
    """``(prose, segment count)``: the rewritable segments of ``source`` joined by blank lines."""
    try:
        segments = io.extract(source, fmt, opts)
    except io.FormatError as e:
        raise RouteError(str(e)) from None
    if not segments:
        raise RouteError(f"the {fmt} file has no rewritable text")
    texts = [s["text"] for s in segments]
    if any(_BLOCK_BREAK.search(t) for t in texts):
        raise RouteError("a segment contains a blank line; use the manual Files route")
    return SEGMENT_BREAK.join(texts), len(texts)


def blocks(text):
    """The blank-line separated blocks of a rewrite (one per segment)."""
    return [b for b in _BLOCK_BREAK.split(text.strip()) if b.strip()]


def segment_issues(rewrite, count):
    """An issue when the rewrite no longer has one block per segment of the source file."""
    got = len(blocks(rewrite))
    if got == count:
        return []
    return [{"type": "segment_count_changed", "expected": count, "got": got,
             "hint": "keep one blank-line separated block per segment of the source file"}]


def rebuild_file(source, fmt, rewrite, opts=None):
    """The source file with each segment replaced by the matching block of ``rewrite``."""
    segments = io.extract(source, fmt, opts)
    return io.rebuild(source, fmt, {s["id"]: b for s, b in zip(segments, blocks(rewrite))}, opts)


# --- Long -------------------------------------------------------------------------------------

def is_long(text):
    """Whether ``text`` is above the chunking threshold."""
    return chunk.size(text) > chunk.DEFAULT_THRESHOLD


def chunks(masked, lang_code):
    """The masked text split into chunks; ``"".join(chunks) == masked``."""
    return chunk.split(masked, threshold=0, lang_code=lang_code)[0]


def sentence_chunks(original, restored_chunks, lang_code, keep=()):
    """Map each original sentence id to the 0-based index of the chunk it starts in."""
    bounds, pos = [], 0
    for text in restored_chunks:
        pos += len(text)
        bounds.append(pos)
    spans = Doc(original, lang.load(lang_code), keep).spans
    return {i: next(k for k, end in enumerate(bounds) if start < end or k == len(bounds) - 1)
            for i, (start, _) in enumerate(spans, 1)}


def merge(inputs, rewrites):
    """Join rewritten chunks, keeping each input chunk's trailing whitespace (paragraph breaks)."""
    return "".join(r.rstrip() + i[len(i.rstrip()):] for i, r in zip(inputs, rewrites))


def last_paragraph(text):
    """The last paragraph of ``text``: read-only context for the next chunk."""
    parts = blocks(text)
    return parts[-1] if parts else ""


def plan_chunk_errors(plan, of_sentence):
    """Errors where a plan row spans chunks or rows leave chunk order (long sessions)."""
    errors, last = [], 0
    for n, row in enumerate(plan["rows"], 1):
        where = sorted({of_sentence[i] + 1 for i in row["src"] if i in of_sentence})
        if len(where) > 1:
            errors.append({"type": "plan_crosses_chunk", "row": n, "src": row["src"], "chunks": where})
        elif where and where[0] < last:
            errors.append({"type": "plan_chunk_order", "row": n, "src": row["src"], "chunk": where[0],
                           "after_chunk": last})
        if where:
            last = max(last, where[-1])
    return errors


def default_glossary(original):
    """Glossary when pass 1 gave none: the recurring terms that must be kept verbatim."""
    return [e for e in glossary.extract(original) if e["decision"] == glossary.KEEP]


def glossary_errors(entries):
    """Errors for an ``analysis.json`` glossary list."""
    try:
        glossary.parse(entries)
    except glossary.GlossaryError as e:
        return [{"type": "invalid_glossary", "error": str(e)}]
    return []


def glossary_issues(original, rewrite, entries):
    """Glossary decisions the rewrite does not follow."""
    return glossary.verify(original, rewrite, entries)["warnings"]


# --- Variants ---------------------------------------------------------------------------------

def validate_variants(data, count, validate_one):
    """``(errors, warnings)`` of a plan with ``count`` variants, each with a distinct axis.

    ``validate_one`` validates a single ``{"rows", "axis"}`` plan; its issues are tagged with
    the variant id.
    """
    if not isinstance(data, dict) or set(data) != {"variants"} or not isinstance(data["variants"], list):
        return [{"type": "invalid_artifact",
                 "error": 'a variant plan must be {"variants": [{"axis": str, "rows": [...]}, ...]}'}], []
    plans = data["variants"]
    errors, warnings = [], []
    if len(plans) != count:
        errors.append({"type": "variant_count", "expected": count, "got": len(plans)})
    axes = []
    for k, plan in enumerate(plans, 1):
        vid = f"v{k}"
        axis = plan.get("axis") if isinstance(plan, dict) else None
        if not isinstance(axis, str) or not axis.strip():
            errors.append({"type": "variant_axis_missing", "variant": vid})
        elif axis.strip().lower() in axes:
            errors.append({"type": "variant_axis_duplicate", "variant": vid, "axis": axis})
        else:
            axes.append(axis.strip().lower())
        e, w = validate_one(plan)
        errors += [dict(i, variant=vid) for i in e]
        warnings += [dict(i, variant=vid) for i in w]
    return errors, warnings


def pairwise_issues(pairs, units):
    """``variants_too_similar`` issues from ``metrics.pairwise`` results."""
    return [{"type": "variants_too_similar", "variants": [units[p["a"]], units[p["b"]]],
             "overlap": p["overlap"], "hint": f"rewrite {units[p['b']]} along a different axis"}
            for p in pairs["too_similar"]]

