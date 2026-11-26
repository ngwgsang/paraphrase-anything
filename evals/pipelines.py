"""Compare one-shot rewriting with the harness presets on the eval cases (story 028).

No LLM is called. Each case holds the agent's drafts: ``rewrite`` (faithful) and, for ``drift``
cases, ``drift.rewrite`` (a first attempt whose meaning drifted in a way ``pe check`` misses).
A scripted agent replays those drafts through a real harness session: it writes the drift draft
first, judges entailment as a competent judge would (``drift.forward`` / ``drift.backward`` on
the drifted pair, ``entail`` elsewhere), and switches to the faithful draft only when a gate
reports the drift. The runs therefore measure what each pipeline verifies and what it costs
(steps, fix rounds); they do not measure how well a live model writes or judges.
"""

import json
import shutil
import tempfile
from pathlib import Path

from paraphrase_everything import check, harness, metrics, planning, protect

PIPELINES = ("one-shot", "fast", "standard", "strict")
CATEGORIES = ("prose", "technical", "academic", "accept_warning", "drift")
CATCH_ISSUES = ("entailment_failed", "fact_changed", "fact_lost")
MAX_STEPS = 50
FACT_CHARS = 100


class PipelineError(RuntimeError):
    """Raised when a scripted run cannot be driven (a case or harness regression)."""


def eligible(case):
    """Whether ``case`` has a single plain-text rewrite to replay through the pipelines."""
    return case.get("category") in CATEGORIES and "rewrite" in case and "expect" not in case


def _norm(text):
    """``text`` with whitespace collapsed, for comparisons."""
    return " ".join(text.split())


def _final_scores(case, text):
    """Fidelity and divergence of the text a pipeline delivered, scored against the original."""
    original, code = case["input"], case.get("lang", "en")
    chk = check.check(original, text, lang_code=code, accept=case.get("accept", []))
    cmp = metrics.compare(original, text, lang_code=code, mode=case.get("mode"))
    return {"check_errors": len(chk["errors"]), "check_warnings": len(chk["warnings"]),
            "accepted_warnings": len(chk["accepted"]), "overlap": cmp["overlap"],
            "length_ratio": cmp["length_ratio"]}


def _drifted(case, text):
    """Whether ``text`` is the drift draft of ``case``."""
    drift = case.get("drift")
    return bool(drift) and _norm(text) == _norm(drift["rewrite"])


def one_shot(case):
    """One draft, no harness: the first attempt ships with only the advisory ``pe check``."""
    text = case["drift"]["rewrite"] if case.get("drift") else case["rewrite"]
    return dict(_final_scores(case, text), pipeline="one-shot", status="complete", steps=1, fix_rounds=0,
                caught=0, drift=bool(case.get("drift")), drift_shipped=_drifted(case, text), facts=None)


def _plan(case, text):
    """A plan whose rows map the original sentences onto ``text`` (from the ``pe check`` aligner)."""
    code = case.get("lang", "en")
    src = [s["text"] for s in planning.sentences(case["input"], code)]
    out = [s["text"] for s in planning.sentences(text, code)]
    groups, mean = check.align(src, out)
    if mean > check.LOW_CONFIDENCE:
        groups = [(list(range(len(src))), list(range(len(out))))]
    rows = []
    for ai, bi in groups:
        if not ai:
            continue
        if len(ai) > 1 and len(ai) == len(bi):  # n-to-n: one reworded sentence each
            rows += [{"src": [i + 1], "ops": ["lexical"], "target": 1} for i in ai]
            continue
        if len(ai) > 1 and len(bi) > 1:
            raise PipelineError(f"{case['id']}: the aligner grouped {len(ai)} sentences into {len(bi)}")
        ops = ["merge"] if len(ai) > 1 else ["split"] if len(bi) > 1 else ["lexical"]
        rows.append({"src": [i + 1 for i in ai], "ops": ops, "target": len(bi)})
    return {"rows": rows}


def _analysis(case):
    """Pass 1 output: one fact per original sentence, anchored on the case's expected numbers."""
    numbers = case.get("expected_invariants", {}).get("numbers", [])
    facts = []
    for s in planning.sentences(case["input"], case.get("lang", "en"))[:12]:
        text = s["text"].strip()
        facts.append({"id": f"f{s['id']}", "fact": text if len(text) <= FACT_CHARS else text[:FACT_CHARS - 1] + "…",
                      "anchors": [n for n in numbers if n in text]})
    return {"facts": facts, "constraints": {"keep": [], "length_ratio": None}, "discourse": [], "register": "neutral"}


def _masked(text, original):
    """``text`` with each protected span of ``original`` replaced by its placeholder."""
    _, mapping = protect.protect(original)
    for key, item in sorted(mapping["placeholders"].items(), key=lambda kv: -len(kv[1]["text"])):
        text = text.replace(item["text"], protect.PLACEHOLDER.format(key[1:]), 1)
    return text


def _judge(case, session_dir, drafting_drift):
    """Write the entailment verdicts for the current rewrite; return the drifted source ids."""
    found = harness.entailment_pairs(session_dir)
    drift, bad_src, pairs = case.get("drift"), set(), []
    for p in found["pairs"]:
        drifted = drafting_drift and _norm(p["rewritten"]) not in _norm(case["rewrite"])
        item = {"pair": p["pair"], "forward": "entail", "backward": "entail",
                "evidence": {"src": p["original"], "rew": p["rewritten"]},
                "reason": "the flagged change keeps the meaning" if p["flags"] else ""}
        if drifted:
            item.update(forward=drift["forward"], backward=drift["backward"], reason=drift["reason"])
            bad_src.update(p["src"])
        pairs.append(item)
    _write(Path(found["file"]), {"judge": "self", "pairs": pairs})
    return bad_src


def _write(path, data):
    """Write ``data`` (text or JSON) as UTF-8."""
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    Path(path).write_text(text, encoding="utf-8", newline="")


def _act(case, session_dir, task, caught):
    """Do one task as the scripted agent; return how many agent steps it took."""
    if task["step"] == "analysis":
        _write(task["output"], _analysis(case))
        return 1
    if task["step"] == "plan":
        _write(task["output"], _plan(case, case["rewrite"]))
        return 1
    drafting_drift = bool(case.get("drift")) and not caught
    text = case["drift"]["rewrite"] if drafting_drift else case["rewrite"]
    _write(task["output"], _masked(text, case["input"]))
    review, steps, bad_src = {"accept": case.get("accept", [])}, 1, set()
    if task.get("entailment"):
        bad_src = _judge(case, session_dir, drafting_drift)
        steps += 1
    if "state" in task and task.get("review_required") is not None:
        # facts are one per sentence (``_analysis``): a fact changes when its sentence drifted
        changed = {f"f{i}" for i in bad_src}
        review["verdicts"] = [{"id": f["id"], "verdict": "changed" if f["id"] in changed else "kept",
                               "note": case["drift"]["reason"] if f["id"] in changed else ""}
                              for f in task["state"]["facts"]]
    _write(task["review"], review)
    return steps


def _facts(report):
    """Fact verdict counts of a session report, or None without pass 1."""
    found = report["facts"]
    if not found:
        return None
    return {"total": found["total"], "kept": found["kept"],
            **{k: len(found[k]) for k in ("changed", "lost", "unjudged")}}


def run_preset(case, preset):
    """Replay ``case`` through a harness session with ``preset``; return the run's measurements."""
    tmp = Path(tempfile.mkdtemp(prefix="pe-eval-"))
    session_dir = tmp / "session"
    try:
        harness.init(case["input"], session_dir=session_dir, mode=case.get("mode") or "standard",
                     lang_code=case.get("lang", "en"), preset=preset)
        steps = caught = 0
        for _ in range(MAX_STEPS):
            task = harness.next_task(session_dir)
            if task["step"] in ("done", "incomplete"):
                break
            steps += _act(case, session_dir, task, caught)
            caught += sum(1 for i in harness.submit(session_dir)["issues"] if i["type"] in CATCH_ISSUES)
        else:
            raise PipelineError(f"{case['id']} ({preset}): no result after {MAX_STEPS} steps")
        report = harness.write_report(session_dir)
        history = harness.load(session_dir)["history"]
        text = Path(report["output"]).read_text(encoding="utf-8") if report["output"] else case["input"]
        return dict(_final_scores(case, text), pipeline=preset, status=report["status"], steps=steps,
                    fix_rounds=sum(1 for e in history if not e["ok"]), caught=caught,
                    drift=bool(case.get("drift")), drift_shipped=_drifted(case, text), facts=_facts(report),
                    open_issues=[i["type"] for i in report["open_issues"]])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_case(case, pipelines):
    """Every selected pipeline's run of ``case``, each tagged with the case id and language."""
    runs = []
    for name in pipelines:
        run = one_shot(case) if name == "one-shot" else run_preset(case, name)
        runs.append(dict(run, id=case["id"], lang=case.get("lang", "en")))
    return runs


def _mean(values):
    """Mean of the non-None ``values``, rounded, or None."""
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else None


def summarize(runs, pipelines):
    """Per-pipeline totals: completion, drift caught and shipped, fidelity, divergence, cost."""
    summary = {}
    for name in pipelines:
        own = [r for r in runs if r["pipeline"] == name]
        drift = [r for r in own if r["drift"]]
        facts = [r["facts"] for r in own if r["facts"]]
        summary[name] = {
            "runs": len(own),
            "complete": sum(1 for r in own if r["status"] == "complete"),
            "drift_cases": len(drift),
            "drift_caught": sum(1 for r in drift if r["caught"]),
            "drift_shipped": sum(1 for r in drift if r["drift_shipped"]),
            "check_errors": sum(r["check_errors"] for r in own),
            "check_warnings": sum(r["check_warnings"] for r in own),
            "facts_judged": sum(f["total"] for f in facts) if facts else None,
            "mean_overlap": _mean(r["overlap"] for r in own),
            "mean_length_ratio": _mean(r["length_ratio"] for r in own),
            "fix_rounds": sum(r["fix_rounds"] for r in own),
            "steps": sum(r["steps"] for r in own),
            "mean_steps": _mean(r["steps"] for r in own),
        }
    return summary


def compare(cases, pipelines=PIPELINES):
    """Run every eligible case through ``pipelines``; return ``{ok, pipelines, summary, runs}``.

    ``ok`` is False when a scripted run did not complete: every case is written to finish.
    """
    runs = [run for case in cases if eligible(case) for run in run_case(case, pipelines)]
    return {"ok": all(r["status"] == "complete" for r in runs), "pipelines": list(pipelines),
            "summary": summarize(runs, pipelines), "runs": runs}


COLUMNS = (("runs", "runs"), ("drift_caught", "caught"), ("drift_shipped", "shipped"),
           ("check_errors", "errors"), ("check_warnings", "warns"), ("facts_judged", "facts"),
           ("mean_overlap", "overlap"), ("mean_length_ratio", "length"), ("fix_rounds", "rounds"),
           ("steps", "steps"), ("mean_steps", "steps/run"))


def build_table(summary):
    """Format the per-pipeline summary as a text table ('-' = not measured)."""
    lines = [f"{'Pipeline':<10}" + "".join(f"{head:<10}" for _, head in COLUMNS)]
    for name, row in summary.items():
        cells = ("-" if row[key] is None else str(row[key]) for key, _ in COLUMNS)
        lines.append(f"{name:<10}" + "".join(f"{c:<10}" for c in cells))
    return "\n".join(lines)
