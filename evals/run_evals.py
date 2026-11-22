"""Evaluation suite runner for paraphrase-everything (story 011).

Evaluates fixed (pre-written) rewrites across languages (en, vi, ja) for fidelity, divergence metrics,
pairwise diversity, and prompt trigger accuracy. Generates a summary table and a JSON report.
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

from paraphrase_everything import check, lang, metrics, protect

TRIGGERS_FILE = ROOT / "evals" / "triggers.json"
SKILL_MD = ROOT / "skills" / "paraphrase-anything" / "SKILL.md"
POSITIVE_MARKER = "Use when the user asks to "
POSITIVE_END = ", for pasted"


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


def evaluate_case(case):
    """Run fidelity checks, metrics, or triggers for a single eval case dict."""
    case_id = case["id"]
    lang_code = case.get("lang", "en")
    category = case.get("category", "prose")
    result = {
        "id": case_id,
        "lang": lang_code,
        "category": category,
        "ok": True,
        "fidelity": "N/A",
        "overlap": None,
        "details": {},
    }

    if category == "triggers":
        prompts = case.get("prompts", [])
        positive = skill_trigger_terms()
        negative = load_negative_terms()
        mismatches = []
        for item in prompts:
            predicted = evaluate_prompt_trigger(item["prompt"], lang_code, positive, negative)
            expected = item["expected_trigger"]
            if predicted != expected:
                mismatches.append({"prompt": item["prompt"], "expected": expected, "got": predicted})
        result["ok"] = len(mismatches) == 0
        result["fidelity"] = "PASS" if result["ok"] else "FAIL"
        result["details"]["trigger_mismatches"] = mismatches
        return result

    if category == "variants":
        variants = case.get("variants", [])
        original = case.get("input", "")
        var_failures = []
        for i, var in enumerate(variants):
            chk = check.check(original, var, lang_code=lang_code)
            if not chk["ok"]:
                var_failures.append({"index": i, "errors": chk["errors"]})
        pair_rep = metrics.pairwise(variants, lang_code=lang_code)
        result["ok"] = (len(var_failures) == 0) and pair_rep["ok"]
        result["fidelity"] = "PASS" if not var_failures else "FAIL"
        result["details"]["variant_failures"] = var_failures
        result["details"]["pairwise"] = pair_rep
        result["overlap"] = round(sum(p["overlap"] for p in pair_rep["pairs"]) / len(pair_rep["pairs"]), 3) \
            if pair_rep["pairs"] else None
        return result

    # Prose / technical / accept_warning rewrite evaluation
    original = case.get("input", "")
    rewrite = case.get("rewrite", "")
    accept = case.get("accept", [])

    if case.get("format") == "structured":
        try:
            masked, mapping = protect.protect(original)
            masked_rewrite = case.get("masked_rewrite")
            if masked_rewrite:
                restored, rest_rep = protect.restore(masked_rewrite, mapping)
                if not rest_rep["ok"]:
                    result["ok"] = False
                    result["details"]["protect_errors"] = rest_rep
                if restored != rewrite:
                    result["ok"] = False
                    result["details"]["restore_mismatch"] = {"expected": rewrite, "got": restored}
            else:
                restored, rest_rep = protect.restore(rewrite, mapping)
                if not rest_rep["ok"]:
                    result["ok"] = False
                    result["details"]["protect_errors"] = rest_rep
        except Exception as e:
            result["ok"] = False
            result["details"]["protect_exception"] = str(e)

    chk = check.check(original, rewrite, lang_code=lang_code, accept=accept)
    cmp = metrics.compare(original, rewrite, lang_code=lang_code, mode=case.get("mode"))

    # Invariants verification
    invariants = case.get("expected_invariants", {})
    missing_invariants = []
    for num in invariants.get("numbers", []):
        if num not in rewrite:
            missing_invariants.append(f"number:{num}")
    for code_span in invariants.get("code", []):
        if code_span not in rewrite:
            missing_invariants.append(f"code:{code_span}")
    for url in invariants.get("urls", []):
        if url not in rewrite:
            missing_invariants.append(f"url:{url}")

    result["fidelity"] = "PASS" if (chk["ok"] and not missing_invariants) else "FAIL"
    result["overlap"] = cmp.get("overlap")
    result["details"]["check"] = chk
    result["details"]["metrics"] = cmp
    result["details"]["missing_invariants"] = missing_invariants
    result["ok"] = result["ok"] and chk["ok"] and cmp["ok"] and (len(missing_invariants) == 0)
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


def run_evals(cases_dir=None, json_path=None, lang_filter=None, quiet=False):
    """Run all evaluation cases, write JSON report, and return (exit_code, report_dict)."""
    cases_dir = Path(cases_dir) if cases_dir else ROOT / "evals" / "cases"
    json_path = Path(json_path) if json_path else ROOT / "evals" / "report.json"

    cases = load_cases(cases_dir, lang_filter=lang_filter)
    if not cases:
        raise RuntimeError(f"No evaluation cases found in {cases_dir}")

    results = [evaluate_case(case) for case in cases]
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    pass_rate = round(passed / total, 4) if total else 0.0

    by_lang = {}
    for r in results:
        code = r["lang"]
        group = by_lang.setdefault(code, {"total": 0, "passed": 0})
        group["total"] += 1
        if r["ok"]:
            group["passed"] += 1

    for group in by_lang.values():
        group["pass_rate"] = round(group["passed"] / group["total"], 4)

    report = {
        "ok": passed == total,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": pass_rate,
        "by_lang": by_lang,
        "results": results,
    }

    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not quiet:
        print(f"\nEVALUATION SUMMARY: {passed} / {total} passed ({pass_rate * 100:.1f}%)")
        print(build_summary_table(results))
        print("Language Breakdown:")
        for code, group in sorted(by_lang.items()):
            print(f"  {code}: {group['passed']}/{group['total']} passed ({group['pass_rate'] * 100:.1f}%)")
        print(f"Report written to: {json_path}\n")

    return (0 if report["ok"] else 1), report


def main():
    """CLI entry point for running the evaluation suite."""
    parser = argparse.ArgumentParser(description="Paraphrase-everything evaluation suite runner")
    parser.add_argument("--cases", default=str(ROOT / "evals" / "cases"), help="Directory with eval cases")
    parser.add_argument("--json", default=str(ROOT / "evals" / "report.json"), help="Output path for JSON report")
    parser.add_argument("--lang", choices=["en", "vi", "ja"], help="Filter cases by language")
    parser.add_argument("--quiet", action="store_true", help="Suppress summary table output")
    args = parser.parse_args()

    try:
        exit_code, _ = run_evals(cases_dir=args.cases, json_path=args.json,
                                 lang_filter=args.lang, quiet=args.quiet)
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
