"""Key-fact checklist: validate facts against the original and verify a rewrite (story 021).

The LLM lists the few load-bearing facts and later judges each one; this module checks what
code can: the list is short and grounded in the original, anchors survive the rewrite, and
every fact received a verdict.
"""

import re

from . import lang
from .check import NUMBER_RE, _numbers
from .text import normalize, term_pattern

MAX_FACTS = 12
MAX_FACT_CHARS = 120
VERDICTS = ("kept", "changed", "lost")


class FactsError(ValueError):
    """Raised when the facts or verdicts input is malformed."""


def parse_facts(data):
    """Validate the shape of a facts list and return it normalised."""
    if not isinstance(data, list) or not data:
        raise FactsError("facts must be a non-empty JSON list")
    facts, seen = [], set()
    for item in data:
        if not isinstance(item, dict):
            raise FactsError("each fact must be an object with id, fact, anchors")
        fid, text = item.get("id"), item.get("fact")
        anchors = item.get("anchors", [])
        if not isinstance(fid, str) or not fid.strip():
            raise FactsError("each fact needs a non-empty string id")
        if fid in seen:
            raise FactsError(f"duplicate fact id: {fid}")
        seen.add(fid)
        if not isinstance(text, str) or not text.strip():
            raise FactsError(f"fact {fid} needs a non-empty string 'fact'")
        if not isinstance(anchors, list) or not all(isinstance(a, str) and a.strip() for a in anchors):
            raise FactsError(f"fact {fid}: anchors must be a list of non-empty strings")
        facts.append({"id": fid, "fact": text.strip(), "anchors": [a.strip() for a in anchors]})
    return facts


def parse_verdicts(data):
    """Validate a verdict list and return {fact id: {verdict, note}}."""
    if not isinstance(data, list):
        raise FactsError("verdicts must be a JSON list")
    verdicts = {}
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise FactsError("each verdict must be an object with an id")
        if item.get("verdict") not in VERDICTS:
            raise FactsError(f"verdict for {item['id']} must be one of: {', '.join(VERDICTS)}")
        if item["id"] in verdicts:
            raise FactsError(f"duplicate verdict for {item['id']}")
        verdicts[item["id"]] = {"verdict": item["verdict"], "note": str(item.get("note", ""))}
    return verdicts


def _is_number(anchor):
    """Whether the anchor is a bare number such as 42, 3.5 or 1,000."""
    return NUMBER_RE.fullmatch(normalize(anchor)) is not None


def _anchor_in(anchor, text, data, numbers):
    """Whether ``anchor`` occurs in ``text``: numbers by value, other anchors as words/terms."""
    if _is_number(anchor):
        return all(key in numbers for key in _numbers(anchor, data))
    pattern = term_pattern(normalize(anchor), data["match"] == "word", re.IGNORECASE)
    return pattern.search(normalize(text)) is not None


def verify(original, facts, rewritten=None, verdicts=None, lang_code="auto", max_facts=MAX_FACTS):
    """Validate ``facts`` against ``original``; with ``rewritten``, also verify them.

    ``verdicts`` (from :func:`parse_verdicts`) are the LLM's per-fact judgements.
    """
    code = lang.detect(original) if lang_code == "auto" else lang_code
    data = lang.load(code)
    errors, warnings = [], []

    if len(facts) > max_facts:
        errors.append({"type": "too_many_facts", "count": len(facts), "max": max_facts})
    orig_numbers = _numbers(original, data)
    new_numbers = _numbers(rewritten, data) if rewritten is not None else None

    for fact in facts:
        fid = fact["id"]
        if len(fact["fact"]) > MAX_FACT_CHARS:
            errors.append({"type": "fact_too_long", "id": fid, "chars": len(fact["fact"]),
                           "max": MAX_FACT_CHARS})
        if not fact["anchors"]:
            warnings.append({"type": "fact_without_anchor", "id": fid})
        for anchor in fact["anchors"]:
            if not _anchor_in(anchor, original, data, orig_numbers):
                errors.append({"type": "anchor_not_in_original", "id": fid, "anchor": anchor})
            elif rewritten is not None and not _anchor_in(anchor, rewritten, data, new_numbers):
                errors.append({"type": "anchor_missing", "id": fid, "anchor": anchor})

    if rewritten is not None:
        if verdicts is None:
            warnings.append({"type": "no_verdicts"})
        else:
            ids = {f["id"] for f in facts}
            for unknown in sorted(set(verdicts) - ids):
                errors.append({"type": "verdict_unknown_id", "id": unknown})
            for fact in facts:
                verdict = verdicts.get(fact["id"])
                if verdict is None:
                    errors.append({"type": "verdict_missing", "id": fact["id"]})
                elif verdict["verdict"] != "kept":
                    errors.append({"type": f"fact_{verdict['verdict']}", "id": fact["id"],
                                   "note": verdict["note"]})

    report = {"ok": not errors, "stage": "validate" if rewritten is None else "verify",
              "lang": code, "total": len(facts)}
    if rewritten is not None:
        failing = {e["id"] for e in errors if "id" in e}
        report["kept"] = len([f for f in facts if f["id"] not in failing])
    report["errors"], report["warnings"] = errors, warnings
    return report
