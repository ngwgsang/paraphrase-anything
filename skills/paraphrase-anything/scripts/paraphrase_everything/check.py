"""Deterministic fidelity check between an original and its rewrite (story 002).

Errors are certain and must be fixed. Warnings are suspicious and may be accepted
with a reason, because legitimate rewrites ("not uncommon" -> "common") trip them.
"""

import math
import re
from collections import Counter

from . import lang
from .protect import PLACEHOLDER_RE, find_spans
from .text import count, markers_pattern, normalize, split_sentences

CITATION_RE = re.compile(
    r"\[\d+(?:\s*[,–-]\s*\d+)*\]"                       # [1], [1, 2], [3-5]
    r"|\([^()\d]*[^\W\d_][^()]*?,?\s*\d{4}[a-z]?\)"     # (Smith, 2020), (Smith et al. 2020a)
)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
WORD_RE = re.compile(r"[^\W\d_][\w'’-]*")

SKIP_COST = 1.2       # cost of leaving a sentence unaligned
MERGE_PENALTY = 0.3   # extra cost per merged sentence in a group
LOW_CONFIDENCE = 1.5  # mean group cost above this -> document-level comparison
SNIPPET = 120


class Doc:
    """Text analysed once: opaque spans removed, sentences split."""

    def __init__(self, raw, data, keep):
        """Analyse ``raw``: strip opaque spans and citations, then split sentences."""
        self.raw = raw
        spans = find_spans(raw, keep)
        self.opaque = Counter(raw[s:e] for s, e, _ in spans)
        # Blank out opaque spans (same length) so numbers in URLs/code are ignored.
        chars = list(raw)
        for s, e, _ in spans:
            chars[s:e] = " " * (e - s)
        self.text = "".join(chars)
        self.citations = Counter(m.group(0) for m in CITATION_RE.finditer(self.text))
        self.prose = CITATION_RE.sub(lambda m: " " * len(m.group(0)), self.text)
        self.spans = split_sentences(self.prose, data)
        self.sentences = [self.prose[s:e] for s, e in self.spans]


def _numbers(text, data):
    """Count numeric values, normalised with the language's separators."""
    values = Counter()
    for m in NUMBER_RE.finditer(normalize(text)):
        token = m.group(0).replace(data["thousands_separator"], "")
        token = token.replace(data["decimal_separator"], ".")
        try:
            values[repr(float(token))] += 1
        except ValueError:  # e.g. "1.2.3" (version, date) - compare verbatim
            values[m.group(0)] += 1
    return values


def _pretty_number(key):
    """Format a normalised number key for display (42.0 -> 42)."""
    try:
        f = float(key)
        return str(int(f)) if f.is_integer() else str(f)
    except ValueError:
        return key


def _trigrams(s):
    """Set of lower-cased character trigrams, whitespace collapsed."""
    s = re.sub(r"\s+", " ", normalize(s).lower())
    return {s[i:i + 3] for i in range(max(len(s) - 2, 1))}


def align(a, b):
    """Monotonic alignment of sentence lists, allowing 1:0, 0:1, 1:1, 1:2, 2:1, 1:3, 3:1, 2:2.

    Cost mixes length ratio (Gale-Church style) with char-trigram dissimilarity,
    so it tolerates heavy rewording as long as order is roughly kept.
    Returns ``(groups, mean_cost)`` with groups as ``(a_indices, b_indices)``.
    """
    moves = [(1, 1), (1, 2), (2, 1), (1, 3), (3, 1), (2, 2), (1, 0), (0, 1)]
    n, m = len(a), len(b)
    tri_a, tri_b = [_trigrams(x) for x in a], [_trigrams(x) for x in b]
    inf = math.inf
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    band = max(6, abs(n - m) + 4)

    len_a = [0]
    for x in a:
        len_a.append(len_a[-1] + len(x))
    len_b = [0]
    for x in b:
        len_b.append(len_b[-1] + len(x))
    unions = {}

    def union(tris, side, i, d):
        """Cached union of trigram sets for ``d`` consecutive sentences from ``i``."""
        if d == 1:
            return tris[i]
        key = (side, i, d)
        if key not in unions:
            unions[key] = set().union(*tris[i:i + d])
        return unions[key]

    def group_cost(i, j, di, dj):
        """Cost of aligning sentences a[i:i+di] with b[j:j+dj]."""
        if di == 0 or dj == 0:
            return SKIP_COST
        la, lb = len_a[i + di] - len_a[i], len_b[j + dj] - len_b[j]
        ta, tb = union(tri_a, "a", i, di), union(tri_b, "b", j, dj)
        dice = 2 * len(ta & tb) / (len(ta) + len(tb)) if ta or tb else 1.0
        return abs(math.log((lb + 1) / (la + 1))) + (1 - dice) + MERGE_PENALTY * (di + dj - 2)

    for i in range(n + 1):
        for j in range(m + 1):
            if cost[i][j] == inf:
                continue
            for di, dj in moves:
                ni, nj = i + di, j + dj
                if ni > n or nj > m or abs(ni * (m / max(n, 1)) - nj) > band:
                    continue
                c = cost[i][j] + group_cost(i, j, di, dj)
                if c < cost[ni][nj]:
                    cost[ni][nj], back[ni][nj] = c, (di, dj)

    groups, i, j = [], n, m
    while i or j:
        di, dj = back[i][j]
        groups.append((list(range(i - di, i)), list(range(j - dj, j))))
        i, j = i - di, j - dj
    groups.reverse()
    paired = [g for g in groups if g[0] and g[1]]
    mean = cost[n][m] / max(len(groups), 1)
    return groups, mean if paired else inf


def _snippet(doc, idx):
    """Raw text of the given sentences (with URLs, code, citations intact)."""
    s = " ".join(doc.raw[doc.spans[k][0]:doc.spans[k][1]] for k in idx)
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= SNIPPET else s[:SNIPPET - 1] + "…"


def _counter_diff(kind, before, after, fmt=str):
    """Report values missing from or extra in ``after`` compared to ``before``."""
    issues = []
    for value, n in (before - after).items():
        issues.append({"type": f"{kind}_missing", "value": fmt(value), "count": n})
    for value, n in (after - before).items():
        issues.append({"type": f"{kind}_extra", "value": fmt(value), "count": n})
    return issues


def _proper_nouns(doc):
    """Capitalised words that are not sentence-initial."""
    names = Counter()
    for sentence in doc.sentences:
        for w in WORD_RE.findall(sentence)[1:]:
            if w[0].isupper() and len(w) > 1:
                names[w] += 1
    return names


def check(original, rewritten, lang_code="auto", keep=(), accept=()):
    """Compare ``rewritten`` against ``original``; return a JSON-serialisable report."""
    code = lang.detect(original) if lang_code == "auto" else lang_code
    data = lang.load(code)
    a, b = Doc(original, data, keep), Doc(rewritten, data, keep)
    errors, warnings, unsupported = [], [], []

    # --- errors: certain ---------------------------------------------------
    for m in PLACEHOLDER_RE.finditer(rewritten):
        errors.append({"type": "placeholder_leftover", "value": m.group(0)})
    errors += _counter_diff("protected_span", a.opaque, b.opaque)
    errors += _counter_diff("citation", a.citations, b.citations)
    errors += _counter_diff("number", _numbers(a.prose, data), _numbers(b.prose, data), _pretty_number)

    # --- warnings: suspicious ----------------------------------------------
    word_bounded = data["match"] == "word"
    neg = markers_pattern(data["negation_markers"], word_bounded)
    hedge = markers_pattern(data["hedge_markers"], word_bounded)
    if neg is None:
        unsupported.append("negation")
    if hedge is None:
        unsupported.append("hedge")

    groups, mean_cost = align(a.sentences, b.sentences)
    if mean_cost > LOW_CONFIDENCE:
        alignment = "document"
        groups = [(list(range(len(a.sentences))), list(range(len(b.sentences))))]
    else:
        alignment = "sentence"

    for ai, bi in groups:
        where = {"original": _snippet(a, ai), "rewritten": _snippet(b, bi),
                 "original_sentences": ai, "rewritten_sentences": bi}
        if not bi:
            warnings.append({"type": "sentence_unaligned", **where})  # possible omission
            continue
        if not ai:
            warnings.append({"type": "sentence_added", **where})  # possible new claim
            continue
        ta = " ".join(a.sentences[k] for k in ai)
        tb = " ".join(b.sentences[k] for k in bi)
        for kind, pattern in (("negation", neg), ("hedge", hedge)):
            ca, cb = count(pattern, ta), count(pattern, tb)
            if ca != cb:
                warnings.append({"type": f"{kind}_mismatch", "original_count": ca,
                                 "rewritten_count": cb, **where})

    if data["has_case"]:
        words_b = set(WORD_RE.findall(b.prose))
        for name in sorted(_proper_nouns(a)):
            if name not in words_b:
                warnings.append({"type": "proper_noun_missing", "value": name})
    else:
        unsupported.append("proper_noun")

    # --- ids and accepts ----------------------------------------------------
    for n, e in enumerate(errors, 1):
        e["id"] = f"e{n}"
    for n, w in enumerate(warnings, 1):
        w["id"] = f"w{n}"

    by_id = {w["id"]: w for w in warnings}
    accepted, rejected = [], []
    for item in accept:
        wid, reason = item.get("id"), (item.get("reason") or "").strip()
        if wid in by_id and reason:
            accepted.append({**by_id.pop(wid), "reason": reason})
        else:
            why = "error ids cannot be accepted" if str(wid).startswith("e") else \
                  "missing reason" if wid in by_id else "unknown id"
            rejected.append({"id": wid, "why": why})

    return {
        "ok": not errors and not by_id,
        "lang": code,
        "alignment": alignment,
        "errors": errors,
        "warnings": list(by_id.values()),
        "accepted": accepted,
        "rejected_accepts": rejected,
        "unsupported": unsupported,
    }
