"""Session harness: ``pe run`` owns the workflow and hands the agent one task at a time (story 022).

The agent never picks the next step. It calls ``next``, writes the one artifact it is asked
for, and calls ``submit``; the harness runs that pass's gate against the original, then
advances, sends the same pass back with the issues, or ends the session as ``incomplete``.
All state lives in ``session.json`` so a session survives process restarts.

Text passes (story 024) work on a masked copy of the original: protected spans become
placeholders, every gate restores them before comparing with the original, and the finished
rewrite is written restored to ``output.txt``.
"""

import hashlib
import json
import tempfile
from pathlib import Path

from . import check, facts, lang, metrics, planning, protect

SKILL_DIR = Path(__file__).resolve().parents[2]
REFERENCES = SKILL_DIR / "references"
SESSION_FILE = "session.json"
ORIGINAL_FILE = "original.txt"
MASKED_FILE = "masked.txt"
OUTPUT_FILE = "output.txt"
REPORT_FILE = "report.json"
GATES_DIR = "gates"
DEFAULT_MAX_ROUNDS = 2
SCHEMA_VERSION = 2

# Every pass in pipeline order. ``ops`` are the plan ops a text pass applies; a disabled text
# pass merges its ops and duties into the next enabled text pass. JSON passes are frozen once
# their gate passes, because later gates rely on them.
PASSES = [
    {"id": "analysis", "gate": "g1", "artifact": "analysis.json", "kind": "json",
     "references": ["analysis.md", "facts.md"], "ops": [],
     "duties": ["list the key facts, constraints, discourse relations, and register of the original"]},
    {"id": "plan", "gate": "g2", "artifact": "plan.json", "kind": "json",
     "references": ["plan.md", "modes.md"], "ops": [],
     "duties": ["plan the change for every original sentence"]},
    {"id": "structure", "gate": "g3", "artifact": "p3-structure.txt", "kind": "text",
     "references": ["layers.md"], "ops": ["split", "merge", "reorder"],
     "duties": ["change sentence structure only; keep the wording as close to the original as possible"]},
    {"id": "lexis", "gate": "g4", "artifact": "p4-lexis.txt", "kind": "text",
     "references": ["layers.md"], "ops": ["voice", "clause", "lexical"],
     "duties": ["change wording inside sentences; never add, remove, split, or merge sentences"]},
    {"id": "style", "gate": "g5", "artifact": "p5-style.txt", "kind": "text",
     "references": ["layers.md", "modes.md", "preservation.md"], "ops": ["register", "shorten", "expand"],
     "duties": ["apply the mode, persona, register, and length target; add no new claims"]},
]
BY_ID = {p["id"]: p for p in PASSES}
FINAL_PASS = "style"
STRUCTURE_OPS = set(BY_ID["structure"]["ops"])
COUNT_CHANGING_OPS = STRUCTURE_OPS | {"shorten", "expand"}


class HarnessError(Exception):
    """A usage or integrity error: the command cannot run (exit code 2)."""


# --- files and hashes -----------------------------------------------------------------------

def _sha256(path):
    """Hex SHA-256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_text(path):
    """Read UTF-8 text without changing line endings."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def _write_text(path, text):
    """Write UTF-8 text without changing line endings."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _write_json(path, data):
    """Write ``data`` as indented UTF-8 JSON."""
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _review_name(artifact):
    """Name of the optional review file (accepts, verdicts) that goes with a text artifact."""
    return Path(artifact).stem + ".review.json"


# --- session state --------------------------------------------------------------------------

def load(session_dir):
    """Load and integrity-check a session; raise ``HarnessError`` on tampering or bad state."""
    session_dir = Path(session_dir)
    path = session_dir / SESSION_FILE
    if not path.is_file():
        raise HarnessError(f"not a session directory: {session_dir}")
    try:
        state = json.loads(_read_text(path))
    except json.JSONDecodeError as e:
        raise HarnessError(f"{SESSION_FILE} is not valid JSON: {e}") from None
    if state.get("version") != SCHEMA_VERSION:
        raise HarnessError(f"session format {state.get('version')} is not supported; start a new session")
    original = session_dir / ORIGINAL_FILE
    if not original.is_file() or _sha256(original) != state["original_sha256"]:
        raise HarnessError(f"{ORIGINAL_FILE} changed after init; start a new session")
    for pid, digest in state["frozen"].items():
        artifact = session_dir / BY_ID[pid]["artifact"]
        if not artifact.is_file() or _sha256(artifact) != digest:
            raise HarnessError(f"{BY_ID[pid]['artifact']} is frozen; change it only with "
                               f"'pe run rewind <session-dir> --to {pid}'")
    return state


def save(session_dir, state):
    """Persist the session state."""
    _write_json(Path(session_dir) / SESSION_FILE, state)


def parse_passes(spec):
    """Turn a ``--passes`` value into an ordered list of enabled pass ids."""
    if spec is None:
        return [p["id"] for p in PASSES]
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    for pid in wanted:
        if pid not in BY_ID:
            raise HarnessError(f"unknown pass: {pid} (choose from {', '.join(BY_ID)})")
    if FINAL_PASS not in wanted:
        raise HarnessError(f"pass {FINAL_PASS} cannot be disabled: it produces the rewrite")
    return [p["id"] for p in PASSES if p["id"] in wanted]


def init(text, session_dir=None, mode="standard", persona=None, lang_code="auto", passes=None,
         max_rounds=DEFAULT_MAX_ROUNDS):
    """Create a session for ``text`` and return its state; ``session_dir`` defaults to a temp dir."""
    if not text.strip():
        raise HarnessError("input is empty")
    if protect.PLACEHOLDER_RE.search(text):
        raise HarnessError("input already contains placeholder-like text (⟦P<n>⟧)")
    if mode not in metrics.MODES:
        raise HarnessError(f"unknown mode {mode!r}; choose from {', '.join(metrics.MODES)}")
    if persona and not (REFERENCES / "personas" / f"{persona}.md").is_file():
        raise HarnessError(f"unknown persona {persona!r}; see references/personas/")
    if max_rounds < 0:
        raise HarnessError("--max-rounds must be 0 or more")
    enabled = parse_passes(passes)
    if session_dir is None:
        session_dir = tempfile.mkdtemp(prefix="pe-")
    session_dir = Path(session_dir)
    if (session_dir / SESSION_FILE).exists():
        raise HarnessError(f"a session already exists in {session_dir}")
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / GATES_DIR).mkdir(exist_ok=True)
    _write_text(session_dir / ORIGINAL_FILE, text)
    state = {
        "version": SCHEMA_VERSION,
        "original_sha256": _sha256(session_dir / ORIGINAL_FILE),
        "lang": lang.detect(text) if lang_code == "auto" else lang_code,
        "mode": mode,
        "persona": persona,
        "passes": enabled,
        "gates_skipped": [p["gate"] for p in PASSES if p["id"] not in enabled],
        "max_rounds": max_rounds,
        "rounds": {pid: 0 for pid in enabled},
        "current": enabled[0],
        "status": "in_progress",
        "frozen": {},
        "history": [],
    }
    save(session_dir, state)
    return dict(state, session_dir=str(session_dir))


# --- derived state --------------------------------------------------------------------------

def _frozen_json(session_dir, state, pid):
    """Content of the frozen JSON artifact of ``pid``, or None if it is not frozen."""
    if pid not in state["frozen"]:
        return None
    return json.loads(_read_text(Path(session_dir) / BY_ID[pid]["artifact"]))


def frozen_analysis(session_dir, state):
    """The frozen ``analysis.json`` content, or None before gate 1 passed (or without pass 1)."""
    return _frozen_json(session_dir, state, "analysis")


def _constraints(analysis):
    """``(keep terms, length ratio)`` from the frozen analysis."""
    constraints = (analysis or {}).get("constraints", {})
    return tuple(constraints.get("keep", ())), constraints.get("length_ratio")


def _masking(original, keep):
    """``(masked text, placeholder mapping)`` of the original with the given keep terms."""
    return protect.protect(original, keep)


def _text_passes(state):
    """Enabled text passes in order."""
    return [pid for pid in state["passes"] if BY_ID[pid]["kind"] == "text"]


def responsibilities(state, pid):
    """``(ops, duties, merged passes)`` of text pass ``pid``, including disabled passes before it."""
    ops, duties, merged = [], [], []
    for p in PASSES:
        if p["kind"] != "text":
            continue
        if p["id"] == pid:
            return ops + p["ops"], duties + p["duties"], merged
        if p["id"] not in state["passes"]:
            ops += p["ops"]
            duties += p["duties"]
            merged.append(p["id"])
    raise HarnessError(f"{pid} is not a text pass")


def _previous_pass(state, pid):
    """The enabled text pass before ``pid``, or None."""
    passes = _text_passes(state)
    index = passes.index(pid)
    return passes[index - 1] if index else None


def _plan_for(state, pid, plan):
    """Plan rows as the task of ``pid`` sees them: only its ops, and its sentence targets."""
    ops = set(responsibilities(state, pid)[0])
    drops_done = "shorten" in ops or _drops_done_before(state, pid)
    rows = []
    for n, row in enumerate(plan["rows"], 1):
        mine = [o for o in row["ops"] if o in ops]
        if row["ops"] == ["keep"]:
            mine = ["keep"]
        target = row["target"] if row["target"] or drops_done else 1
        rows.append({"row": n, "src": row["src"], "ops": mine, "target": target})
    return rows


def _drops_done_before(state, pid):
    """Whether an earlier enabled text pass was responsible for ``shorten`` (drops)."""
    passes = _text_passes(state)
    return any("shorten" in responsibilities(state, p)[0] for p in passes[:passes.index(pid)])


# --- tasks ----------------------------------------------------------------------------------

def _references(state, pid):
    """Absolute paths of the reference files this pass needs, and nothing else."""
    names = list(BY_ID[pid]["references"])
    if pid in ("lexis", FINAL_PASS):
        names.append(f"languages/{state['lang']}.md")
    if pid == FINAL_PASS and state["persona"]:
        names.append(f"personas/{state['persona']}.md")
    return [str(REFERENCES / n) for n in dict.fromkeys(names) if (REFERENCES / n).is_file()]


def _last_issues(state, pid):
    """Open issues from the latest gate result of ``pid`` (empty when it has not failed)."""
    for entry in reversed(state["history"]):
        if entry["pass"] == pid and not entry.get("invalidated"):
            return [] if entry["ok"] else entry["issues"]
    return []


def next_task(session_dir):
    """Return the single next task, or a terminal ``done`` / ``incomplete`` step."""
    session_dir = Path(session_dir)
    state = load(session_dir)
    if state["status"] == "complete":
        return {"step": "done", "status": "complete", "output": str(session_dir / OUTPUT_FILE),
                "report": str(session_dir / REPORT_FILE)}
    if state["status"] == "incomplete":
        return {"step": "incomplete", "status": "incomplete", "open_issues": open_issues(state)}
    pid = state["current"]
    spec = BY_ID[pid]
    original = _read_text(session_dir / ORIGINAL_FILE)
    analysis = frozen_analysis(session_dir, state)
    plan = _frozen_json(session_dir, state, "plan")
    keep, ratio = _constraints(analysis)
    task = {
        "step": pid,
        "gate": spec["gate"],
        "pass": f"{state['passes'].index(pid) + 1}/{len(state['passes'])}",
        "inputs": {"original": str(session_dir / ORIGINAL_FILE)},
        "output": str(session_dir / spec["artifact"]),
        "instructions": _references(state, pid),
        "duties": spec["duties"],
        "constraints": {
            "lang": state["lang"], "mode": state["mode"], "persona": state["persona"],
            "protected": sorted({original[s:e] for s, e, _ in protect.find_spans(original, keep)}),
            "length_ratio": ratio,
        },
        "round": state["rounds"][pid],
        "max_rounds": state["max_rounds"],
        "issues": _last_issues(state, pid),
    }
    if spec["kind"] == "json":
        task["sentences"] = planning.sentences(original, state["lang"], keep)
    if pid == "analysis":
        task["output_format"] = {"facts": [{"id": "f1", "fact": "short claim", "anchors": ["42"]}],
                                 "constraints": {"keep": [], "length_ratio": None},
                                 "discourse": [{"from": 1, "to": 2, "type": "cause"}],
                                 "register": "neutral"}
    if pid == "plan":
        task["output_format"] = {"rows": [{"src": [1], "ops": ["lexical"], "target": 1}], "axis": None}
    if spec["kind"] == "text":
        ops, duties, merged = responsibilities(state, pid)
        previous = _previous_pass(state, pid)
        if previous is None:
            masked, mapping = _masking(original, keep)
            _write_text(session_dir / MASKED_FILE, masked)
            source = session_dir / MASKED_FILE
        else:
            source = session_dir / BY_ID[previous]["artifact"]
            mapping = _masking(original, keep)[1]
        task["inputs"]["previous"] = str(source)
        task.update(duties=duties, ops=ops, merged_passes=merged)
        task["constraints"]["placeholders"] = [protect.PLACEHOLDER.format(k[1:]) for k in mapping["placeholders"]]
        if plan:
            task["plan"] = _plan_for(state, pid, plan)
        task["review"] = str(session_dir / _review_name(spec["artifact"]))
        task["review_format"] = {"accept": [{"id": "w1", "reason": "why the warning is a false positive"}],
                                 "verdicts": [{"id": "f1", "verdict": "kept", "note": ""}]}
        if analysis and pid == state["passes"][-1]:
            task["review_required"] = ["verdicts: one per fact in state.facts"]
    if analysis:
        task["state"] = {"facts": analysis["facts"], "analysis": analysis}
    return task


# --- gates ----------------------------------------------------------------------------------

def _issue(kind, **fields):
    """A gate issue: one thing the agent must fix (or accept, for warnings)."""
    return dict(fields, type=kind)


def _read_json_artifact(session_dir, pid):
    """Parse the JSON artifact of ``pid``; return ``(data, None)`` or ``(None, issue)``."""
    try:
        return json.loads(_read_text(Path(session_dir) / BY_ID[pid]["artifact"])), None
    except json.JSONDecodeError as e:
        return None, _issue("invalid_artifact", error=f"{BY_ID[pid]['artifact']} is not valid JSON: {e}")


def _gate_analysis(session_dir, state, original):
    """Gate 1: facts grounded in the original; valid constraints, discourse ids, and register."""
    data, problem = _read_json_artifact(session_dir, "analysis")
    if problem:
        return {"ok": False, "issues": [problem], "advisory": {}}
    errors, warnings = planning.validate_analysis(data, original, state["lang"])
    return {"ok": not errors, "issues": errors, "advisory": {"warnings": warnings}}


def _gate_plan(session_dir, state, original):
    """Gate 2: every sentence covered exactly once with known ops and consistent targets."""
    data, problem = _read_json_artifact(session_dir, "plan")
    if problem:
        return {"ok": False, "issues": [problem], "advisory": {}}
    errors, warnings = planning.validate_plan(data, original, state["lang"], state["mode"],
                                              frozen_analysis(session_dir, state))
    return {"ok": not errors, "issues": errors, "advisory": {"warnings": warnings}}


def _read_review(session_dir, artifact):
    """The review file of a text artifact (``{}`` if absent); raise ``FactsError`` if malformed."""
    path = Path(session_dir) / _review_name(artifact)
    if not path.is_file():
        return {}
    try:
        review = json.loads(_read_text(path))
    except json.JSONDecodeError as e:
        raise facts.FactsError(f"{path.name} is not valid JSON: {e}") from None
    if not isinstance(review, dict):
        raise facts.FactsError(f"{path.name} must be an object with 'accept' and/or 'verdicts'")
    return review


def restored_text(session_dir, state, pid):
    """``(restored text, placeholder issues)`` of the text artifact of ``pid``."""
    original = _read_text(Path(session_dir) / ORIGINAL_FILE)
    keep = _constraints(frozen_analysis(session_dir, state))[0]
    mapping = _masking(original, keep)[1]
    restored, report = protect.restore(_read_text(Path(session_dir) / BY_ID[pid]["artifact"]), mapping)
    return restored, report["issues"]


def _gate_text(session_dir, state, original, pid):
    """Gates 3–5: ``pe check`` against the original, plan adherence, sentence count, facts."""
    artifact = BY_ID[pid]["artifact"]
    try:
        review = _read_review(session_dir, artifact)
        accept = review.get("accept", [])
        if not isinstance(accept, list):
            raise facts.FactsError("'accept' must be a list of {id, reason}")
        verdicts = facts.parse_verdicts(review["verdicts"]) if "verdicts" in review else None
    except facts.FactsError as e:
        return {"ok": False, "issues": [_issue("invalid_review", error=str(e))], "advisory": {}}

    analysis = frozen_analysis(session_dir, state)
    plan = _frozen_json(session_dir, state, "plan")
    keep, ratio = _constraints(analysis)
    last = pid == state["passes"][-1]
    ops = set(responsibilities(state, pid)[0])
    rewrite, issues = restored_text(session_dir, state, pid)

    chk = check.check(original, rewrite, lang_code=state["lang"], keep=keep, accept=accept)
    issues += chk["errors"] + chk["warnings"]
    issues += [_issue("rejected_accept", **r) for r in chk["rejected_accepts"]]

    if plan and (ops & STRUCTURE_OPS or last):
        # The pass that owns structure, and the last pass, must match the plan's sentence map.
        drops_done = "shorten" in ops or _drops_done_before(state, pid)
        issues += planning.adherence(plan, original, rewrite, state["lang"], keep, drops_done)
    elif not ops & COUNT_CHANGING_OPS and _previous_pass(state, pid):
        before = restored_text(session_dir, state, _previous_pass(state, pid))[0]
        counts = [len(planning.sentences(t, state["lang"], keep)) for t in (before, rewrite)]
        if counts[0] != counts[1]:
            issues.append(_issue("sentence_count_changed", expected=counts[0], got=counts[1]))

    # An explicit length target is enforced at the last text gate; bands stay advisory.
    cmp = metrics.compare(original, rewrite, lang_code=state["lang"], mode=state["mode"],
                          target_ratio=ratio if last else None)
    if not cmp["ok"]:
        issues.append(_issue("length_target", **cmp["target"], length_ratio=cmp["length_ratio"]))
    result = {"accepted": chk["accepted"], "advisory": {"metrics": cmp, "unsupported": chk["unsupported"]}}
    if analysis:
        # Anchors are checked at every text gate; verdicts are required at the last one.
        report = facts.verify(original, analysis["facts"], rewrite, (verdicts or {}) if last else verdicts,
                              lang_code=state["lang"])
        issues += report["errors"]
        result["advisory"]["facts"] = report["warnings"]
    result.update(ok=not issues, issues=issues)
    return result


def run_gate(session_dir, state, pid):
    """Run the gate of pass ``pid`` against the original."""
    original = _read_text(Path(session_dir) / ORIGINAL_FILE)
    if pid == "analysis":
        return _gate_analysis(session_dir, state, original)
    if pid == "plan":
        return _gate_plan(session_dir, state, original)
    return _gate_text(session_dir, state, original, pid)


def submit(session_dir):
    """Gate the current pass's artifact, record the result, then advance, retry, or stop."""
    session_dir = Path(session_dir)
    state = load(session_dir)
    if state["status"] != "in_progress":
        raise HarnessError(f"session is {state['status']}; nothing to submit")
    pid = state["current"]
    spec = BY_ID[pid]
    artifact = session_dir / spec["artifact"]
    if not artifact.is_file():
        raise HarnessError(f"expected artifact is missing: {artifact}")

    result = run_gate(session_dir, state, pid)
    entry = {"pass": pid, "gate": spec["gate"], "round": state["rounds"][pid], "ok": result["ok"],
             "issues": result["issues"], "accepted": result.get("accepted", []),
             "advisory": result.get("advisory", {})}
    _write_json(session_dir / GATES_DIR / f"{spec['gate']}-{pid}-r{entry['round']}.json", entry)
    state["history"].append(entry)

    if result["ok"]:
        if spec["kind"] == "json":
            state["frozen"][pid] = _sha256(artifact)
        later = state["passes"].index(pid) + 1
        if later < len(state["passes"]):
            state["current"] = state["passes"][later]
        else:
            state["current"], state["status"] = None, "complete"
            _write_text(session_dir / OUTPUT_FILE, restored_text(session_dir, state, pid)[0])
    elif state["rounds"][pid] >= state["max_rounds"]:
        state["status"] = "incomplete"
    else:
        state["rounds"][pid] += 1
    save(session_dir, state)
    if state["status"] != "in_progress":
        write_report(session_dir, state)
    return {"ok": result["ok"], "pass": pid, "gate": spec["gate"], "round": entry["round"],
            "status": state["status"], "next": state["current"], "issues": result["issues"]}


# --- rewind, status, report -----------------------------------------------------------------

def rewind(session_dir, to):
    """Invalidate pass ``to`` and every later pass; the session resumes at ``to``."""
    session_dir = Path(session_dir)
    state = load(session_dir)
    if to not in state["passes"]:
        raise HarnessError(f"pass {to!r} is not enabled in this session ({', '.join(state['passes'])})")
    if state["status"] == "in_progress" and state["passes"].index(to) > state["passes"].index(state["current"]):
        raise HarnessError(f"cannot rewind forward: the session is at {state['current']}")
    dropped = state["passes"][state["passes"].index(to):]
    for pid in dropped:
        artifact = BY_ID[pid]["artifact"]
        for name in (artifact, _review_name(artifact)):
            path = session_dir / name
            if path.is_file():
                path.unlink()
        state["rounds"][pid] = 0
        state["frozen"].pop(pid, None)
    for entry in state["history"]:
        if entry["pass"] in dropped:
            entry["invalidated"] = True
    state["current"], state["status"] = to, "in_progress"
    for name in (REPORT_FILE, OUTPUT_FILE, MASKED_FILE):
        if (session_dir / name).is_file():
            (session_dir / name).unlink()
    save(session_dir, state)
    return {"ok": True, "current": to, "invalidated": dropped}


def open_issues(state):
    """Issues of the latest failed gate that was never passed afterwards."""
    latest = {}
    for entry in state["history"]:
        if not entry.get("invalidated"):
            latest[entry["pass"]] = entry
    return [dict(issue, gate=e["gate"], **{"pass": e["pass"]})
            for e in latest.values() if not e["ok"] for issue in e["issues"]]


def status(session_dir):
    """Current step, rounds used, and the gate history."""
    state = load(session_dir)
    return {"status": state["status"], "current": state["current"], "passes": state["passes"],
            "rounds": state["rounds"], "max_rounds": state["max_rounds"],
            "frozen": [BY_ID[pid]["artifact"] for pid in state["frozen"]],
            "history": [dict({k: e[k] for k in ("pass", "gate", "round", "ok")},
                             invalidated=e.get("invalidated", False)) for e in state["history"]]}


def build_report(session_dir, state):
    """The session report: what ran, what was skipped, what is still open."""
    session_dir = Path(session_dir)
    live = [e for e in state["history"] if not e.get("invalidated")]
    return {
        "status": state["status"],
        "lang": state["lang"], "mode": state["mode"], "persona": state["persona"],
        "passes_run": [e["pass"] for e in live if e["ok"]],
        "gates_run": [{"gate": e["gate"], "pass": e["pass"], "round": e["round"], "ok": e["ok"]} for e in live],
        "gates_skipped": state["gates_skipped"],
        "open_issues": open_issues(state),
        "accepted_warnings": [a for e in live if e["ok"] for a in e["accepted"]],
        "facts_frozen": "analysis" in state["frozen"],
        "output": str(session_dir / OUTPUT_FILE) if state["status"] == "complete" else None,
    }


def write_report(session_dir, state=None):
    """Write ``report.json`` and return the report."""
    state = load(session_dir) if state is None else state
    report = build_report(session_dir, state)
    _write_json(Path(session_dir) / REPORT_FILE, report)
    return report
