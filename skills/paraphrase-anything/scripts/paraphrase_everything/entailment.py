"""Agent-judged bidirectional entailment, verified for completeness by code (story 025).

The agent judges whether each source unit and its rewrite entail each other, in both
directions, and quotes literal evidence from both sides. Code never judges meaning: it builds
the pair list, then enforces that every pair has both verdicts, the evidence is real, verdicts
other than ``entail`` fail, and verdicts that contradict a ``pe check`` warning carry a reason.

``forward`` is original ⊨ rewrite (the rewrite adds nothing); ``backward`` is rewrite ⊨
original (the rewrite loses nothing).
"""

from . import check, planning

VERDICTS = ("entail", "neutral", "contradict")
JUDGES = ("self", "independent")
FLAGGED_WARNINGS = ("negation_mismatch", "hedge_mismatch")


def _norm(text):
    """``text`` with runs of whitespace collapsed, for literal comparisons."""
    return " ".join(text.split())


def _pair(pid, src, original, rewritten, may_drop):
    """One pair to judge."""
    return {"pair": pid, "src": src, "original": original, "rewritten": rewritten,
            "may_drop": may_drop, "flags": []}


def pairs(original, rewrite, lang_code, keep=(), plan=None, mode="standard"):
    """``(pairs, basis)`` to judge; ``pairs`` is None when the rewrite cannot be split by the plan.

    With a plan, each plan row is one pair (``r<row>``) and its output sentences come from the
    plan segmentation (story 024); rows that drop everything have no pair. Without a plan, pairs
    come from the deterministic aligner of ``pe check`` (``a<n>``). Pairs whose two sides are
    identical are skipped. ``may_drop`` marks pairs where ``backward`` may be ``neutral``: rows
    with the ``shorten`` op, or every pair in ``shorten`` mode when there is no plan.
    """
    src = planning.sentences(original, lang_code, keep)
    out = [s["text"] for s in planning.sentences(rewrite, lang_code, keep)]
    result = []
    if plan:
        rows = plan["rows"]
        groups = planning.segment(rows, {s["id"]: s["text"] for s in src}, out)
        if groups is None:
            return None, "plan"
        by_id = {s["id"]: s["text"] for s in src}
        for n, (row, group) in enumerate(zip(rows, groups), 1):
            if group:
                result.append(_pair(f"r{n}", list(row["src"]), " ".join(by_id[i] for i in row["src"]),
                                    " ".join(out[k] for k in group), "shorten" in row["ops"]))
        basis = "plan"
    else:
        texts = [s["text"] for s in src]
        groups, mean = check.align(texts, out)
        if mean > check.LOW_CONFIDENCE:
            groups = [(list(range(len(texts))), list(range(len(out))))]
        for ai, bi in groups:
            if ai and bi:
                result.append(_pair(f"a{len(result) + 1}", [i + 1 for i in ai], " ".join(texts[i] for i in ai),
                                    " ".join(out[k] for k in bi), mode == "shorten"))
        basis = "aligner"
    return [p for p in result if _norm(p["original"]) != _norm(p["rewritten"])], basis


def flag(pair_list, warnings):
    """Add to each pair the ``pe check`` warning types raised on its source sentences."""
    for w in warnings:
        if w["type"] not in FLAGGED_WARNINGS:
            continue
        ids = {i + 1 for i in w.get("original_sentences", [])}
        for p in pair_list:
            if ids & set(p["src"]) and w["type"] not in p["flags"]:
                p["flags"].append(w["type"])
    return pair_list


def _error(kind, **fields):
    """An entailment error (errors cannot be accepted)."""
    return dict(fields, type=kind)


def validate(data, pair_list):
    """``(errors, judge)`` for the agent's verdicts ``data`` against ``pair_list``."""
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        return [_error("invalid_nli", error="the file must be an object with a 'pairs' list")], None
    judge = data.get("judge", "self")
    errors = []
    if judge not in JUDGES:
        errors.append(_error("invalid_nli", error=f"judge must be one of {', '.join(JUDGES)}"))
        judge = None
    expected = {p["pair"]: p for p in pair_list}
    seen = {}
    for item in data["pairs"]:
        pid = item.get("pair") if isinstance(item, dict) else None
        if pid not in expected:
            errors.append(_error("nli_unknown_pair", pair=pid))
        elif pid in seen:
            errors.append(_error("nli_duplicate_pair", pair=pid))
        else:
            seen[pid] = item
    for pid, p in expected.items():
        item = seen.get(pid)
        if item is None:
            errors.append(_error("nli_missing", pair=pid, original=p["original"], rewritten=p["rewritten"]))
            continue
        errors += _pair_errors(p, item)
    return errors, judge


def _pair_errors(p, item):
    """Errors of one judged pair: verdicts, evidence, failed entailment, unexplained conflicts."""
    where = {"pair": p["pair"], "original": p["original"], "rewritten": p["rewritten"]}
    verdicts = {d: item.get(d) for d in ("forward", "backward")}
    bad = [d for d, v in verdicts.items() if v not in VERDICTS]
    if bad:
        return [_error("nli_missing_verdict", directions=bad, allowed=list(VERDICTS), **where)]
    errors = []
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    for side, text in (("src", p["original"]), ("rew", p["rewritten"])):
        snippet = evidence.get(side)
        if not isinstance(snippet, str) or not snippet.strip() or _norm(snippet) not in _norm(text):
            errors.append(_error("nli_evidence_not_found", side=side, evidence=snippet, **where))
    reason = item.get("reason") if isinstance(item.get("reason"), str) else ""
    for direction, verdict in verdicts.items():
        if verdict == "entail":
            continue
        if direction == "backward" and verdict == "neutral" and p["may_drop"] and reason.strip():
            continue  # planned shortening: the rewrite may lose content the plan dropped
        errors.append(_error("entailment_failed", direction=direction, verdict=verdict,
                             reason=reason, **where))
    if p["flags"] and not reason.strip() and set(verdicts.values()) == {"entail"}:
        errors.append(_error("nli_reason_required", warnings=p["flags"], **where))
    return errors
