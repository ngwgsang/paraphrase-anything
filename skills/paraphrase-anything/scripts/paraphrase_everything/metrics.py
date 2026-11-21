"""Divergence and length metrics (story 004).

Overlap bands are advisory: they are reported as below / within / above and never
fail a run. Only an explicit length target (``target_ratio``) is enforced.
"""

import json
import re
from collections import Counter
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from . import lang
from .text import normalize

MODES = json.loads((Path(__file__).parent / "modes.json").read_text(encoding="utf-8"))
TARGET_TOLERANCE = 0.10       # explicit length targets allow ±10%
COPY_RUN = {"word": 8, "char": 20}  # longest shared run worth reporting, per length unit
MAX_PAIR_OVERLAP = 0.50       # variants above this are too similar
CHRF_ORDER, CHRF_BETA = 6, 2

_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


def tokens(text, data):
    """Lower-cased word tokens, or non-space characters for ``char`` languages."""
    text = normalize(text).lower()
    if data["length_unit"] == "char":
        return [c for c in text if c.isalnum()]
    return _WORD.findall(text)


def _ngrams(seq, n):
    if isinstance(seq, str):  # character n-grams: substrings are cheaper than tuples
        return Counter(seq[i:i + n] for i in range(len(seq) - n + 1))
    return Counter(tuple(seq[i:i + n]) for i in range(len(seq) - n + 1))


def ngram_overlap(a, b, max_n=4):
    """Mean F1 of shared 1..4-grams: 1.0 identical, 0.0 nothing in common."""
    scores = []
    for n in range(1, max_n + 1):
        ga, gb = _ngrams(a, n), _ngrams(b, n)
        total = sum(ga.values()) + sum(gb.values())
        if not total:
            break
        scores.append(2 * sum((ga & gb).values()) / total)
    return sum(scores) / len(scores) if scores else 1.0


def chrf(a, b):
    """chrF (Popović 2015): character n-gram F-beta, whitespace ignored, 0..1."""
    a, b = re.sub(r"\s+", "", a), re.sub(r"\s+", "", b)
    precisions, recalls = [], []
    for n in range(1, CHRF_ORDER + 1):
        ga, gb = _ngrams(a, n), _ngrams(b, n)
        if not ga or not gb:
            break
        hit = sum((ga & gb).values())
        precisions.append(hit / sum(gb.values()))
        recalls.append(hit / sum(ga.values()))
    if not precisions:
        return 1.0 if a == b else 0.0
    p, r = sum(precisions) / len(precisions), sum(recalls) / len(recalls)
    if not p and not r:
        return 0.0
    beta2 = CHRF_BETA ** 2
    return (1 + beta2) * p * r / (beta2 * p + r)


_MOD, _BASE = (1 << 61) - 1, 1_000_003


def _hashes(ids, k):
    """Rolling hashes of every k-gram in ``ids`` (Rabin-Karp)."""
    h, power = 0, pow(_BASE, k - 1, _MOD)
    out = []
    for i, x in enumerate(ids):
        if i >= k:
            h = (h - ids[i - k] * power) % _MOD
        h = (h * _BASE + x) % _MOD
        if i >= k - 1:
            out.append(h)
    return out


def longest_shared_run(a, b):
    """Length and start (in ``a``) of the longest token run present in both.

    Binary search on run length with rolling hashes: O(n log n). Hash hits are
    verified, so the result is exact.
    """
    vocab = {}
    ia = [vocab.setdefault(t, len(vocab) + 1) for t in a]
    ib = [vocab.setdefault(t, len(vocab) + 1) for t in b]

    def shared(k):
        starts = {}
        for j, h in enumerate(_hashes(ib, k)):
            starts.setdefault(h, j)
        for i, h in enumerate(_hashes(ia, k)):
            j = starts.get(h)
            if j is not None and ia[i:i + k] == ib[j:j + k]:
                return i
        return None

    low, high, start = 0, min(len(a), len(b)), 0
    while low < high:
        mid = (low + high + 1) // 2
        pos = shared(mid)
        if pos is None:
            high = mid - 1
        else:
            low, start = mid, pos
    return low, start


def _band(value, band):
    if band is None:
        return None
    low, high = band
    return "below" if value < low else "above" if value > high else "within"


def compare(original, rewritten, lang_code="auto", mode=None, target_ratio=None):
    """Metrics for one original/rewrite pair; JSON-serialisable."""
    code = lang.detect(original) if lang_code == "auto" else lang_code
    data = lang.load(code)
    ta, tb = tokens(original, data), tokens(rewritten, data)
    unit = data["length_unit"]

    # autojunk keeps this near-linear on long, repetitive input; the value is advisory.
    matcher = SequenceMatcher(None, ta, tb)
    run_length, run_start = longest_shared_run(ta, tb)
    joiner = "" if unit == "char" else " "
    result = {
        "ok": True,
        "lang": code,
        "length_unit": unit,
        "length": {"original": len(ta), "rewritten": len(tb)},
        "length_ratio": round(len(tb) / len(ta), 3) if ta else None,
        "overlap": round(ngram_overlap(ta, tb), 3),
        "chrf": round(chrf(normalize(original).lower(), normalize(rewritten).lower()), 3),
        "edit_distance": round(1 - matcher.ratio(), 3),
        "longest_copied_run": {"length": run_length,
                               "text": joiner.join(ta[run_start:run_start + run_length])
                               if run_length >= COPY_RUN[unit] else None},
        "bands": {},
    }

    if mode:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; choose from {', '.join(MODES)}")
        bands = MODES[mode]
        result["mode"] = mode
        result["bands"]["overlap"] = _band(result["overlap"], bands["overlap"])
        if result["length_ratio"] is not None:
            result["bands"]["length_ratio"] = _band(result["length_ratio"], bands["length_ratio"])

    if target_ratio is not None:
        low, high = target_ratio * (1 - TARGET_TOLERANCE), target_ratio * (1 + TARGET_TOLERANCE)
        ratio = result["length_ratio"] or 0
        status = _band(ratio, (low, high))
        result["target"] = {"ratio": target_ratio, "allowed": [round(low, 3), round(high, 3)],
                            "status": status}
        result["ok"] = status == "within"
    return result


def pairwise(texts, lang_code="auto", max_overlap=MAX_PAIR_OVERLAP):
    """Divergence between every pair of variants; flags pairs that are too similar."""
    code = lang.detect(" ".join(texts)) if lang_code == "auto" else lang_code
    data = lang.load(code)
    toks = [tokens(t, data) for t in texts]
    pairs = []
    for i, j in combinations(range(len(texts)), 2):
        overlap = round(ngram_overlap(toks[i], toks[j]), 3)
        pairs.append({"a": i, "b": j, "overlap": overlap,
                      "chrf": round(chrf(normalize(texts[i]).lower(), normalize(texts[j]).lower()), 3),
                      "too_similar": overlap > max_overlap})
    too_similar = [p for p in pairs if p["too_similar"]]
    return {"ok": not too_similar, "lang": code, "count": len(texts),
            "max_overlap": max_overlap, "pairs": pairs, "too_similar": too_similar}
