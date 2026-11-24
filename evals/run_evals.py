"""Evaluation suite runner for paraphrase-everything (story 011).

Evaluates fixed (pre-written) rewrites across languages (en, vi, ja) for fidelity, divergence metrics,
pairwise diversity, format round trips, check fixtures, and prompt trigger accuracy. Produces a
summary table, per-language scores, a decision gate, and a JSON report.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "skills" / "paraphrase-anything" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paraphrase_everything import check, io as formats, lang, metrics, protect

TRIGGERS_FILE = ROOT / "evals" / "triggers.json"
THRESHOLDS_FILE = ROOT / "evals" / "thresholds.json"
SKILL_MD = ROOT / "skills" / "paraphrase-anything" / "SKILL.md"
POSITIVE_MARKER = "Use when the user asks to "
POSITIVE_END = ", for pasted"
SCORE_COLUMNS = (("pass_rate", "pass"), ("check_pass_rate", "check"), ("accepted_warning_rate", "accepted"),
                 ("band_rate", "band"), ("variant_overlap", "var-ovl"), ("trigger_accuracy", "trigger"),
                 ("fixture_accuracy", "fixture"))


def skill_trigger_terms(skill_md=SKILL_MD):
    """Extract the trigger phrases listed in the SKILL.md description."""
    text = Path(skill_md).read_text(encoding="utf-8")
    match = re.search(r"^description: (.*)$", text, re.MULTILINE)
    description = match.group(1) if match else ""
    start = description.find(POSITIVE_MARKER)
    end = description.find(POSITIVE_END, start)
    if start < 0 or end < 0:
        raise RuntimeError(f"cannot find trigger phrases in the description of {skill_md}")
    terms = []
    for chunk in description[start + len(POSITIVE_MARKER):end].split(","):
        for part in re.split(r"\s+or\s+", chunk):
            term = re.sub(r"^(give|and)\s+", "", part.strip().strip('"').strip()).lower()
            if term:
                terms.append(term)
    return terms


def load_negative_terms(path=TRIGGERS_FILE):
    """Load the per-language request phrases that must not trigger the skill."""
    return json.loads(Path(path).read_text(encoding="utf-8"))["negative"]


def load_thresholds(path=THRESHOLDS_FILE):
    """Load the per-language decision-gate thresholds."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_prompt_trigger(prompt_text, lang_code, positive=None, negative=None):
    """Decide whether a prompt triggers the skill, using SKILL.md phrases and the negative list.

    Negative entries are request phrases (verbs), not bare nouns, so "rewrite this summary"
    still triggers while "summarize this article" does not.
    """
    positive = skill_trigger_terms() if positive is None else positive
    negative = load_negative_terms() if negative is None else negative
    lower = prompt_text.lower()
    if any(term in lower for term in negative.get(lang_code, [])):
        return False
    return any(term in lower for term in positive)


def _missing_invariants(case, text):
    """List expected numbers, code spans, URLs, and terms that are absent from ``text``."""
    missing = []
    for kind, label in (("numbers", "number"), ("code", "code"), ("urls", "url"), ("terms", "term")):
        for value in case.get("expected_invariants", {}).get(kind, []):
            if value not in text:
                missing.append(f"{label}:{value}")
    return missing


def _check_stats(chk):
    """Per-case counters taken from a ``check`` report."""
    return {"check_ok": chk["ok"],
            "warnings_raised": len(chk["warnings"]) + len(chk["accepted"]),
            "warnings_accepted": len(chk["accepted"])}


def _outcome(chk):
    """The error and warning types a ``check`` report produced, as sorted lists."""
    return {"ok": chk["ok"],
            "errors": sorted({e["type"] for e in chk["errors"]}),
            "warnings": sorted({w["type"] for w in chk["warnings"]})}


def _expect_mismatches(chk, expect):
    """Compare a ``check`` report against an ``expect`` block; return the fields that differ."""
    got = _outcome(chk)
    mismatches = []
    for key in ("ok", "errors", "warnings"):
        if key in expect:
            want = expect[key] if key == "ok" else sorted(set(expect[key]))
            if got[key] != want:
                mismatches.append({"field": key, "expected": want, "got": got[key]})
    return mismatches


def _new_result(case):
    """The empty result skeleton shared by every category."""
    return {"id": case["id"], "lang": case.get("lang", "en"), "category": case.get("category", "prose"),
            "ok": True, "fidelity": "N/A", "overlap": None, "details": {}, "stats": {}}


def _eval_triggers(case, result):
    """Score a list of prompts against the trigger heuristic."""
    positive, negative = skill_trigger_terms(), load_negative_terms()
    prompts = case.get("prompts", [])
    mismatches = []
    for item in prompts:
        predicted = evaluate_prompt_trigger(item["prompt"], result["lang"], positive, negative)
        if predicted != item["expected_trigger"]:
            mismatches.append({"prompt": item["prompt"], "expected": item["expected_trigger"],
                               "got": predicted})
    result["ok"] = not mismatches
    result["fidelity"] = "PASS" if result["ok"] else "FAIL"
    result["details"]["trigger_mismatches"] = mismatches
    result["stats"] = {"prompts": len(prompts), "prompts_correct": len(prompts) - len(mismatches)}


def _eval_variants(case, result):
    """Check every variant against the original and measure pairwise divergence."""
    original, variants = case.get("input", ""), case.get("variants", [])
    failures, raised = [], 0
    for i, var in enumerate(variants):
        chk = check.check(original, var, lang_code=result["lang"])
        raised += len(chk["warnings"])
        missing = _missing_invariants(case, var)
        if not chk["ok"] or missing:
            failures.append({"index": i, "errors": chk["errors"], "warnings": chk["warnings"],
                             "missing_invariants": missing})
    pair = metrics.pairwise(variants, lang_code=result["lang"])
    mean = round(sum(p["overlap"] for p in pair["pairs"]) / len(pair["pairs"]), 3) if pair["pairs"] else None
    result["ok"] = not failures and pair["ok"]
    result["fidelity"] = "PASS" if not failures else "FAIL"
    result["overlap"] = mean
    result["details"]["variant_failures"] = failures
    result["details"]["pairwise"] = pair
    result["stats"] = {"check_ok": not failures, "warnings_raised": raised, "warnings_accepted": 0,
                       "pair_overlap": mean}


def _restore_problems(case):
    """Round-trip a structured case through ``protect``/``restore``; return the problems found."""
    original, rewrite = case.get("input", ""), case.get("rewrite", "")
    try:
        _, mapping = protect.protect(original)
        restored, report = protect.restore(case.get("masked_rewrite") or rewrite, mapping)
    except Exception as exc:  # report it, do not abort the whole run
        return {"protect_exception": str(exc)}
    problems = {}
    if not report["ok"]:
        problems["protect_errors"] = report
    if case.get("masked_rewrite") and restored != rewrite:
        problems["restore_mismatch"] = {"expected": rewrite, "got": restored}
    return problems


def _score_pair(case, result, original, rewrite, extra_problems, output=None):
    """Shared scoring for one original/rewrite pair: check, metrics, invariants, or ``expect``.

    Invariants are looked up in ``output`` (the whole rebuilt document) when given.
    """
    chk = check.check(original, rewrite, lang_code=result["lang"], accept=case.get("accept", []))
    cmp = metrics.compare(original, rewrite, lang_code=result["lang"], mode=case.get("mode"))
    result["overlap"] = cmp["overlap"]
    result["details"].update(extra_problems, check=chk, metrics=cmp)

    if "expect" in case:  # check fixture: the check report itself is what is scored
        mismatches = _expect_mismatches(chk, case["expect"])
        result["ok"] = not extra_problems and not mismatches
        result["fidelity"] = "MATCH" if not mismatches else "MISMATCH"
        result["details"]["expect_mismatches"] = mismatches
        result["stats"] = {"fixtures": 1, "fixtures_matched": int(not mismatches)}
        return

    missing = _missing_invariants(case, rewrite if output is None else output)
    result["details"]["missing_invariants"] = missing
    result["fidelity"] = "PASS" if chk["ok"] and not missing else "FAIL"
    result["ok"] = not extra_problems and chk["ok"] and cmp["ok"] and not missing
    result["stats"] = _check_stats(chk)
    if case.get("mode"):
        result["stats"]["band"] = cmp["bands"].get("overlap")


def _eval_rewrite(case, result):
    """Score a plain or structured (protected-span) rewrite."""
    problems = _restore_problems(case) if case.get("format") == "structured" else {}
    _score_pair(case, result, case.get("input", ""), case.get("rewrite", ""), problems)


def _skeleton(source, segments):
    """The text outside every segment span, in order."""
    parts, pos = [], 0
    for seg in segments:
        parts.append(source[pos:seg["start"]])
        pos = seg["end"]
    parts.append(source[pos:])
    return parts


def _eval_format(case, result):
    """Rebuild a document from rewritten segments; verify its structure, then score the prose."""
    source, fmt = case["input"], case["format"]
    rewritten = {int(k): v for k, v in case.get("segments", {}).items()}
    try:
        before = formats.extract(source, fmt)
        rebuilt = formats.rebuild(source, fmt, rewritten)
        after = formats.extract(rebuilt, fmt)
    except formats.FormatError as exc:
        result.update(ok=False, fidelity="FAIL")
        result["details"]["format_error"] = str(exc)
        return

    problems = {}
    if len(after) != len(before) or _skeleton(source, before) != _skeleton(rebuilt, after):
        problems["structure_changed"] = True
    wrong = [seg["id"] for seg in after
             if seg["id"] in rewritten and seg["text"] != rewritten[seg["id"]].strip()]
    if wrong:
        problems["segment_mismatch"] = wrong
    if "expected_output" in case and rebuilt != case["expected_output"]:
        problems["output_mismatch"] = {"expected": case["expected_output"], "got": rebuilt}
    if fmt in ("srt", "vtt"):
        result["details"]["subtitle_warnings"] = formats.srt.lint(rebuilt, lang.load(result["lang"])["subtitle"])

    original = "\n\n".join(s["text"] for s in before)
    rewrite = "\n\n".join(s["text"] for s in after)
    _score_pair(case, result, original, rewrite, problems, output=rebuilt)


def evaluate_case(case):
    """Run fidelity checks, metrics, format round trips, or triggers for a single eval case dict."""
    result = _new_result(case)
    if result["category"] == "triggers":
        _eval_triggers(case, result)
    elif result["category"] == "variants":
        _eval_variants(case, result)
    elif case.get("format") in formats.FORMATS:
        _eval_format(case, result)
    else:
        _eval_rewrite(case, result)
    return result


def load_cases(cases_dir, lang_filter=None):
    """Load all JSON case files from cases_dir, optionally filtering by language."""
    cases = []
    for path in sorted(Path(cases_dir).rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if lang_filter and data.get("lang") != lang_filter:
            continue
        cases.append(data)
    return cases


def _rate(num, den):
    """``num / den`` rounded, or None when there is nothing to measure."""
    return round(num / den, 4) if den else None


def score_language(results):
    """Aggregate the per-case stats of one language into its scores (None = not measured)."""
    stats = [r["stats"] for r in results]
    checked = [s for s in stats if "check_ok" in s]
    banded = [s for s in stats if s.get("band") is not None]
    pairs = [s["pair_overlap"] for s in stats if s.get("pair_overlap") is not None]
    passed = sum(1 for r in results if r["ok"])
    return {
        "total": len(results),
        "passed": passed,
        "pass_rate": _rate(passed, len(results)),
        "check_pass_rate": _rate(sum(1 for s in checked if s["check_ok"]), len(checked)),
        # share of correct rewrites that needed at least one accepted warning (false-positive load)
        "accepted_warning_rate": _rate(sum(1 for s in checked if s["warnings_accepted"]), len(checked)),
        "band_rate": _rate(sum(1 for s in banded if s["band"] == "within"), len(banded)),
        "variant_overlap": round(sum(pairs) / len(pairs), 3) if pairs else None,
        "trigger_accuracy": _rate(sum(s.get("prompts_correct", 0) for s in stats),
                                  sum(s.get("prompts", 0) for s in stats)),
        "fixture_accuracy": _rate(sum(s.get("fixtures_matched", 0) for s in stats),
                                  sum(s.get("fixtures", 0) for s in stats)),
    }


def apply_gate(by_lang, thresholds):
    """Compare per-language scores with ``min_<score>`` / ``max_<score>`` thresholds; list every breach.

    A score of None (nothing measured for that language) never breaches a threshold.
    """
    failures = []
    for code, scores in sorted(by_lang.items()):
        for key, limit in thresholds.items():
            bound, _, name = key.partition("_")
            if bound not in ("min", "max") or name not in scores:
                raise RuntimeError(f"unknown threshold {key!r}")
            value = scores[name]
            if value is None:
                continue
            if (bound == "min" and value < limit) or (bound == "max" and value > limit):
                failures.append({"lang": code, "score": name, "value": value, bound: limit})
    return {"ok": not failures, "thresholds": thresholds, "failures": failures}


def build_summary_table(results):
    """Format evaluation results into a human-readable table."""
    lines = [
        "=" * 88,
        f"{'ID':<30} {'Lang':<6} {'Category':<15} {'Fidelity':<10} {'Overlap':<10} {'Status':<8}",
        "-" * 88,
    ]
    for r in results:
        overlap_str = f"{r['overlap']:.3f}" if r["overlap"] is not None else "-"
        status_str = "PASS" if r["ok"] else "FAIL"
        lines.append(f"{r['id']:<30} {r['lang']:<6} {r['category']:<15} {r['fidelity']:<10} {overlap_str:<10} {status_str:<8}")
    lines.append("=" * 88)
    return "\n".join(lines)


def build_language_table(by_lang):
    """Format per-language scores into a human-readable table ('-' = not measured)."""
    lines = [f"{'Lang':<6} {'Cases':<7}" + "".join(f"{head:<10}" for _, head in SCORE_COLUMNS)]
    for code, scores in sorted(by_lang.items()):
        cells = ("-" if scores[key] is None else f"{scores[key]:.3f}" for key, _ in SCORE_COLUMNS)
        lines.append(f"{code:<6} {scores['total']:<7}" + "".join(f"{c:<10}" for c in cells))
    return "\n".join(lines)


def run_evals(cases_dir=None, json_path=None, lang_filter=None, quiet=False, thresholds=None):
    """Run all evaluation cases, write JSON report, and return (exit_code, report_dict)."""
    cases_dir = Path(cases_dir) if cases_dir else ROOT / "evals" / "cases"
    json_path = Path(json_path) if json_path else ROOT / "evals" / "report.json"
    thresholds = load_thresholds() if thresholds is None else thresholds

    cases = load_cases(cases_dir, lang_filter=lang_filter)
    if not cases:
        raise RuntimeError(f"No evaluation cases found in {cases_dir}")

    results = [evaluate_case(case) for case in cases]
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    pass_rate = round(passed / total, 4) if total else 0.0

    grouped = {}
    for r in results:
        grouped.setdefault(r["lang"], []).append(r)
    by_lang = {code: score_language(rs) for code, rs in grouped.items()}
    gate = apply_gate(by_lang, thresholds)

    report = {
        "ok": passed == total and gate["ok"],
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": pass_rate,
        "by_lang": by_lang,
        "gate": gate,
        "results": results,
    }

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not quiet:
        print(f"\nEVALUATION SUMMARY: {passed} / {total} passed ({pass_rate * 100:.1f}%)")
        print(build_summary_table(results))
        print("Language Breakdown:")
        for code, group in sorted(by_lang.items()):
            print(f"  {code}: {group['passed']}/{group['total']} passed ({group['pass_rate'] * 100:.1f}%)")
        print(build_language_table(by_lang))
        print(f"Gate: {'PASS' if gate['ok'] else 'FAIL'}")
        for f in gate["failures"]:
            bound = "min" if "min" in f else "max"
            print(f"  {f['lang']}: {f['score']} = {f['value']} ({bound} {f[bound]})")
        print(f"Report written to: {json_path}\n")

    return (0 if report["ok"] else 1), report


def main():
    """CLI entry point for running the evaluation suite."""
    parser = argparse.ArgumentParser(description="Paraphrase-everything evaluation suite runner")
    parser.add_argument("--cases", default=str(ROOT / "evals" / "cases"), help="Directory with eval cases")
    parser.add_argument("--json", default=str(ROOT / "evals" / "report.json"), help="Output path for JSON report")
    parser.add_argument("--lang", choices=["en", "vi", "ja"], help="Filter cases by language")
    parser.add_argument("--thresholds", default=str(THRESHOLDS_FILE), help="Decision-gate thresholds JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress summary table output")
    args = parser.parse_args()

    try:
        exit_code, _ = run_evals(cases_dir=args.cases, json_path=args.json, lang_filter=args.lang,
                                 quiet=args.quiet, thresholds=load_thresholds(args.thresholds))
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
