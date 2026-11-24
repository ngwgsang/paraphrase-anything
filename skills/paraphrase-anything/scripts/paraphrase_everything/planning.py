"""Passes 1–2: source analysis and per-sentence transformation plan (story 023).

Sentence ids come from the same splitter ``pe check`` uses, so the plan maps every original
sentence to the output sentences later gates expect. Validators return error and warning lists
in the ``check`` style; they never judge meaning.
"""

import math

from . import facts, lang
from .check import Doc, _trigrams

DISCOURSE_TYPES = ("cause", "contrast", "condition", "sequence")
REGISTERS = ("formal", "neutral", "casual", "academic", "technical", "literary")
OPS = ("keep", "split", "merge", "reorder", "voice", "clause", "lexical", "register",
       "shorten", "expand")
STRUCTURAL_OPS = ("split", "merge", "reorder")
MAX_LENGTH_RATIO = 3.0


def sentences(original, lang_code, keep=()):
    """The original's sentences as ``[{"id": 1, "text": ...}, ...]`` (ids are 1-based)."""
    doc = Doc(original, lang.load(lang_code), keep)
    return [{"id": i, "text": original[s:e]} for i, (s, e) in enumerate(doc.spans, 1)]


def _is_int(value):
    """Whether ``value`` is an int and not a bool."""
    return isinstance(value, int) and not isinstance(value, bool)


def validate_analysis(data, original, lang_code):
    """Gate 1: facts, constraints, discourse, and register of ``analysis.json``."""
    if not isinstance(data, dict):
        return [{"type": "invalid_artifact", "error": "analysis must be a JSON object"}], []
    unknown = sorted(set(data) - {"facts", "constraints", "discourse", "register"})
    errors = [{"type": "unknown_key", "key": k} for k in unknown]
    try:
        fact_list = facts.parse_facts(data.get("facts"))
    except facts.FactsError as e:
        return errors + [{"type": "invalid_facts", "error": str(e)}], []
    report = facts.verify(original, fact_list, lang_code=lang_code)
    errors += report["errors"]
    warnings = list(report["warnings"])

    constraints = data.get("constraints", {})
    if not isinstance(constraints, dict):
        errors.append({"type": "invalid_constraints", "error": "constraints must be an object"})
        constraints = {}
    for key in sorted(set(constraints) - {"keep", "length_ratio"}):
        errors.append({"type": "unknown_key", "key": f"constraints.{key}"})
    keep = constraints.get("keep", [])
    if not isinstance(keep, list) or not all(isinstance(k, str) and k.strip() for k in keep):
        errors.append({"type": "invalid_constraints", "error": "constraints.keep must be a list of strings"})
    else:
        errors += [{"type": "keep_not_in_original", "term": k} for k in keep if k not in original]
    ratio = constraints.get("length_ratio")
    if ratio is not None and (isinstance(ratio, bool) or not isinstance(ratio, (int, float))
                              or not 0 < ratio <= MAX_LENGTH_RATIO):
        errors.append({"type": "invalid_constraints",
                       "error": f"constraints.length_ratio must be a number in (0, {MAX_LENGTH_RATIO}]"})

    ids = {s["id"] for s in sentences(original, lang_code, keep if isinstance(keep, list) else ())}
    discourse = data.get("discourse", [])
    if not isinstance(discourse, list):
        errors.append({"type": "invalid_discourse", "error": "discourse must be a list"})
        discourse = []
    for n, rel in enumerate(discourse, 1):
        if not isinstance(rel, dict) or set(rel) - {"from", "to", "type"}:
            errors.append({"type": "invalid_discourse", "index": n, "error": "use {from, to, type}"})
            continue
        if rel.get("type") not in DISCOURSE_TYPES:
            errors.append({"type": "invalid_discourse", "index": n,
                           "error": f"type must be one of {', '.join(DISCOURSE_TYPES)}"})
        for end in ("from", "to"):
            if not _is_int(rel.get(end)) or rel[end] not in ids:
                errors.append({"type": "unknown_sentence", "index": n, "field": end, "value": rel.get(end)})
        if rel.get("from") == rel.get("to"):
            errors.append({"type": "invalid_discourse", "index": n, "error": "from and to must differ"})

    register = data.get("register")
    if register is not None and register not in REGISTERS:
        errors.append({"type": "invalid_register", "value": register, "allowed": list(REGISTERS)})
    return errors, warnings


def _row_errors(n, row, ids, mode):
    """Shape and consistency errors of plan row ``n``; also returns its valid source ids."""
    if not isinstance(row, dict) or set(row) - {"src", "ops", "target", "note"}:
        return [{"type": "invalid_row", "row": n, "error": "use {src, ops, target}"}], []
    errors = []
    src, ops, target = row.get("src"), row.get("ops"), row.get("target")
    if not isinstance(src, list) or not src or not all(_is_int(i) for i in src):
        return [{"type": "invalid_row", "row": n, "error": "src must be a non-empty list of sentence ids"}], []
    errors += [{"type": "unknown_sentence", "row": n, "value": i} for i in src if i not in ids]
    if not isinstance(ops, list) or not ops or not all(isinstance(o, str) for o in ops):
        errors.append({"type": "invalid_row", "row": n, "error": "ops must be a non-empty list"})
        ops = []
    errors += [{"type": "unknown_op", "row": n, "op": o} for o in ops if o not in OPS]
    if "keep" in ops and len(ops) > 1:
        errors.append({"type": "inconsistent_row", "row": n, "error": "keep cannot be combined with other ops"})
    if "split" in ops and "merge" in ops:
        errors.append({"type": "inconsistent_row", "row": n, "error": "a row cannot both split and merge"})
    if len(src) > 1 and "merge" not in ops:
        errors.append({"type": "inconsistent_row", "row": n, "error": "several src ids need the merge op"})
    if "merge" in ops and len(src) < 2:
        errors.append({"type": "inconsistent_row", "row": n, "error": "merge needs at least 2 src ids"})
    if not _is_int(target) or target < 0:
        errors.append({"type": "invalid_row", "row": n, "error": "target must be an integer >= 0"})
    elif target == 0:
        if not (mode == "shorten" and "shorten" in ops):
            errors.append({"type": "inconsistent_target", "row": n,
                           "error": "target 0 (drop) is only allowed with shorten in shorten mode"})
    elif "split" in ops and target < 2:
        errors.append({"type": "inconsistent_target", "row": n, "error": "split needs target >= 2"})
    elif "split" not in ops and target != 1:
        errors.append({"type": "inconsistent_target", "row": n, "error": "without split, target must be 1"})
    return errors, [i for i in src if i in ids]


def validate_plan(data, original, lang_code, mode, analysis=None):
    """Gate 2: every sentence covered once, known ops, targets consistent with ops and mode."""
    if isinstance(data, dict):
        unknown = sorted(set(data) - {"rows", "axis"})
        rows = data.get("rows")
    else:
        unknown, rows = [], None
    if not isinstance(rows, list) or not rows:
        return [{"type": "invalid_artifact", "error": "plan must be {\"rows\": [...], \"axis\"?: str}"}], []
    errors = [{"type": "unknown_key", "key": k} for k in unknown]
    warnings = []
    constraints = (analysis or {}).get("constraints", {})
    ids = [s["id"] for s in sentences(original, lang_code, constraints.get("keep", ()))]
    covered = []
    for n, row in enumerate(rows, 1):
        row_errors, src = _row_errors(n, row, set(ids), mode)
        errors += row_errors
        covered += src
    for sid in ids:
        times = covered.count(sid)
        if times == 0:
            errors.append({"type": "sentence_uncovered", "sentence": sid})
        elif times > 1:
            errors.append({"type": "sentence_covered_twice", "sentence": sid, "count": times})

    all_ops = {o for row in rows if isinstance(row, dict) and isinstance(row.get("ops"), list)
               for o in row["ops"] if isinstance(o, str)}
    if mode == "light":
        for n, row in enumerate(rows, 1):
            ops = row.get("ops") if isinstance(row, dict) else None
            used = [o for o in ops if o in STRUCTURAL_OPS] if isinstance(ops, list) else []
            if used:
                warnings.append({"type": "structural_op_in_light_mode", "row": n, "ops": used})
    ratio = constraints.get("length_ratio")
    wants_shorter = mode == "shorten" or (ratio is not None and ratio < 1)
    wants_longer = mode == "expand" or (ratio is not None and ratio > 1)
    if wants_shorter and "shorten" not in all_ops:
        errors.append({"type": "length_plan_mismatch", "error": "a shorter result needs at least one shorten op"})
    if wants_longer and "expand" not in all_ops:
        errors.append({"type": "length_plan_mismatch", "error": "a longer result needs at least one expand op"})
    if wants_shorter and "expand" in all_ops or wants_longer and "shorten" in all_ops:
        errors.append({"type": "length_plan_mismatch", "error": "shorten and expand ops contradict the length goal"})
    if "axis" in data and not isinstance(data["axis"], str):
        errors.append({"type": "invalid_artifact", "error": "axis must be a string"})
    return errors, warnings


def mapping(plan):
    """Plan rows as ``[{"src": [ids], "target": n, "ops": [...]}, ...]`` in output order.

    Stories 024 (plan adherence) and 025 (entailment pairs) consume this mapping.
    """
    return [{"src": list(r["src"]), "target": r["target"], "ops": list(r["ops"])} for r in plan["rows"]]


MAX_GROUP = 6      # most output sentences one plan row may produce
SKIP_COST = 1.2    # cost of a row that receives no output sentence (same scale as check.align)


def _row_cost(src_text, group_text):
    """Dissimilarity of a row's source text and the output sentences assigned to it."""
    if not group_text:
        return SKIP_COST
    ta, tb = _trigrams(src_text), _trigrams(group_text)
    dice = 2 * len(ta & tb) / (len(ta) + len(tb)) if ta or tb else 1.0
    return abs(math.log((len(group_text) + 1) / (len(src_text) + 1))) + (1 - dice)


def segment(rows, source, output, expected=None):
    """Split ``output`` sentences into one contiguous group per plan row, in row order.

    ``source`` maps sentence id to original text. Rows are in output order, so reordering is
    handled; the split minimises the dissimilarity of each row with its group. ``expected``
    (default: each row's ``target``) bounds the search to a band around the planned counts,
    which keeps long texts fast. Returns one list of output indices per row.
    """
    n, m = len(rows), len(output)
    texts = [" ".join(source[i] for i in row["src"]) for row in rows]
    expected = [r["target"] for r in rows] if expected is None else expected
    prefix = [0]
    for count in expected:
        prefix.append(prefix[-1] + count)
    band = max(MAX_GROUP, abs(m - prefix[-1]) + 4)
    inf = math.inf
    best = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(0, prefix[i] - band), min(m, prefix[i] + band) + 1):
            for size in range(0, min(MAX_GROUP, j) + 1):
                prev = best[i - 1][j - size]
                if prev == inf:
                    continue
                cost = prev + _row_cost(texts[i - 1], " ".join(output[j - size:j]))
                if cost < best[i][j]:
                    best[i][j], back[i][j] = cost, size
    if best[n][m] == inf:  # more output sentences than the rows can absorb
        return None
    groups, j = [], m
    for i in range(n, 0, -1):
        size = back[i][j]
        groups.append(list(range(j - size, j)))
        j -= size
    return groups[::-1]


def adherence(plan, original, rewrite, lang_code, keep=(), drops_done=True):
    """Errors where ``rewrite`` does not follow the plan: sentence count per row and keep rows.

    With ``drops_done`` False, rows with target 0 still expect their one sentence (the drop
    belongs to a later pass).
    """
    rows = plan["rows"]
    source = {s["id"]: s["text"] for s in sentences(original, lang_code, keep)}
    output = [s["text"] for s in sentences(rewrite, lang_code, keep)]
    expected = [r["target"] if r["target"] or drops_done else 1 for r in rows]
    groups = segment(rows, source, output, expected)
    if groups is None:
        return [{"type": "plan_sentence_count", "expected": sum(expected), "got": len(output)}]
    errors = []
    for n, (row, want, group) in enumerate(zip(rows, expected, groups), 1):
        got = " ".join(output[k] for k in group)
        if len(group) != want:
            errors.append({"type": "plan_target_mismatch", "row": n, "src": row["src"],
                           "expected": want, "got": len(group), "rewritten": got})
        elif row["ops"] == ["keep"] and " ".join(got.split()) != " ".join(source[row["src"][0]].split()):
            errors.append({"type": "keep_row_changed", "row": n, "src": row["src"],
                           "original": source[row["src"][0]], "rewritten": got})
    return errors
