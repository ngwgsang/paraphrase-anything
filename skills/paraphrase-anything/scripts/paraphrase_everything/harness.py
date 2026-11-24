"""Session harness: ``pe run`` owns the workflow and hands the agent one task at a time (story 022).

The agent never picks the next step. It calls ``next``, writes the one artifact it is asked
for, and calls ``submit``; the harness runs that pass's gate against the original, then
advances, sends the same pass back with the issues, or ends the session as ``incomplete``.
All state lives in ``session.json`` so a session survives process restarts.

Text passes (story 024) work on a masked copy of the original: protected spans become
placeholders, every gate restores them before comparing with the original, and the finished
rewrite is written restored to ``output.txt``. The last text gate also verifies the agent's
entailment verdicts (story 025). Passes and gates are configurable, with presets; a final floor
check against the original runs in every configuration (story 026).

Routes (story 027): a ``.md`` / ``.srt`` / ``.vtt`` input is rewritten as its prose segments and
rebuilt at the end; a long input is rewritten chunk by chunk inside each text pass, with a
glossary from pass 1; ``variants`` runs every text pass once per variant plan and ends with a
pairwise distinctness gate.
"""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from . import check, entailment, facts, glossary, lang, metrics, planning, protect, routes

SKILL_DIR = Path(__file__).resolve().parents[2]
REFERENCES = SKILL_DIR / "references"
SESSION_FILE = "session.json"
ORIGINAL_FILE = "original.txt"
SOURCE_STEM = "source"
MASKED_FILE = "masked.txt"
MASKED_CHUNKS = "masked.chunks"
OUTPUT_FILE = "output.txt"
REPORT_FILE = "report.json"
GATES_DIR = "gates"
PAIRWISE_GATE = "gv"
DEFAULT_MAX_ROUNDS = 2
SCHEMA_VERSION = 4
PRESETS_FILE = Path(__file__).with_name("presets.json")

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
GATES = [p["gate"] for p in PASSES]
BY_GATE = {p["gate"]: p for p in PASSES}
STRUCTURE_OPS = set(BY_ID["structure"]["ops"])
COUNT_CHANGING_OPS = STRUCTURE_OPS | {"shorten", "expand"}
FORMATS = ("text",) + tuple(routes.FILE_EXTENSIONS)


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


def _nli_name(artifact):
    """Name of the entailment verdicts file that goes with a text artifact."""
    return Path(artifact).stem + ".nli.json"


def _artifact(pid, unit=None):
    """File name of the artifact of ``pid``; text passes get one file per variant ``unit``."""
    name = BY_ID[pid]["artifact"]
    if unit is None or BY_ID[pid]["kind"] != "text":
        return name
    return f"{Path(name).stem}.{unit}{Path(name).suffix}"


def _chunk_dir(artifact):
    """Folder holding the chunk files of a text artifact in a long session."""
    return Path(artifact).stem + ".chunks"


def _output_name(unit=None, ext=".txt"):
    """File name of a finished output (per variant when ``unit`` is given)."""
    return "output" + (f".{unit}" if unit else "") + ext


def _source_name(state):
    """File name of the copied source file of a Files session, or None."""
    fmt = state["format"]
    return SOURCE_STEM + routes.FILE_EXTENSIONS[fmt] if fmt != "text" else None


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
    for name, digest in [(ORIGINAL_FILE, state["original_sha256"])] + \
            ([(_source_name(state), state["source_sha256"])] if _source_name(state) else []):
        if not (session_dir / name).is_file() or _sha256(session_dir / name) != digest:
            raise HarnessError(f"{name} changed after init; start a new session")
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


def parse_gates(spec):
    """Turn a ``--gates`` value (``1,3,5`` or ``g1,g3``; empty for none) into gate ids in order."""
    if spec is None:
        return list(GATES)
    wanted = set()
    for token in (t.strip() for t in spec.split(",")):
        if not token:
            continue
        gate = token if token.startswith("g") else f"g{token}"
        if gate not in BY_GATE:
            raise HarnessError(f"unknown gate: {token} (choose from 1-{len(GATES)})")
        wanted.add(gate)
    return [g for g in GATES if g in wanted]


def presets():
    """The named presets from ``presets.json``."""
    return json.loads(_read_text(PRESETS_FILE))


def resolve(passes, gates):
    """``(active gates, skipped gates, resolutions)`` for the enabled passes and requested gates.

    Every departure from the request is listed, never applied silently: gates of disabled passes
    are dropped, the gate of an enabled JSON pass is kept (later passes rely on its artifact),
    the floor replaces a disabled last gate, and entailment pairs fall back to the aligner
    without a plan.
    """
    active, resolutions = [], []
    for p in PASSES:
        gate, wanted = p["gate"], p["gate"] in gates
        if p["id"] not in passes:
            if wanted:
                resolutions.append({"gate": gate, "action": "dropped", "why": f"pass {p['id']} is disabled"})
        elif wanted:
            active.append(gate)
        elif p["kind"] == "json":
            active.append(gate)
            resolutions.append({"gate": gate, "action": "kept",
                                "why": f"later passes rely on {p['artifact']}; disable pass {p['id']} to skip it"})
    final = BY_ID[passes[-1]]["gate"]
    if final not in active:
        resolutions.append({"gate": final, "action": "floor",
                            "why": "the last gate is disabled; the final floor check still runs"})
    elif "plan" not in passes:
        resolutions.append({"check": "entailment", "action": "aligner",
                            "why": "pass plan is disabled; pairs come from the pe check aligner"})
    return active, [g for g in GATES if g not in active], resolutions


def skipped_checks(state):
    """Names of the checks this configuration does not run, for the report and response line."""
    names = []
    if "analysis" not in state["passes"]:
        names.append("key facts")
    if "plan" not in state["passes"]:
        names.append("plan adherence")
    for pid in ("structure", "lexis"):
        if pid in state["passes"] and BY_ID[pid]["gate"] not in state["gates"]:
            names.append(f"{pid} gate")
    if BY_ID[state["passes"][-1]]["gate"] not in state["gates"]:
        names += ["check warnings", "plan adherence", "length target", "entailment"]
        if state["long"]:
            names.append("glossary")
        if state["variants"]:
            names.append("variant distinctness")
    return list(dict.fromkeys(names))


def init(text, session_dir=None, mode="standard", persona=None, lang_code="auto", passes=None,
         max_rounds=DEFAULT_MAX_ROUNDS, gates=None, preset=None, fmt="text", variants=1):
    """Create a session for ``text`` and return its state; ``session_dir`` defaults to a temp dir.

    ``passes`` and ``gates`` override the preset's; without a preset everything is enabled.
    ``fmt`` is the input format (``text``, ``markdown``, ``srt``, ``vtt``); file formats are
    rewritten as their prose segments. ``variants`` > 1 asks for that many distinct rewrites.
    """
    if fmt not in FORMATS:
        raise HarnessError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}")
    source, segments = text, None
    if fmt != "text":
        try:
            text, segments = routes.file_prose(source, fmt)
        except routes.RouteError as e:
            raise HarnessError(str(e)) from None
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
    if not isinstance(variants, int) or not 1 <= variants <= routes.MAX_VARIANTS:
        raise HarnessError(f"--variants must be between 1 and {routes.MAX_VARIANTS}")
    chosen = {}
    if preset is not None:
        if preset not in presets():
            raise HarnessError(f"unknown preset {preset!r}; choose from {', '.join(presets())}")
        chosen = presets()[preset]
    if passes is None and chosen:
        passes = ",".join(chosen["passes"])
    if gates is None and chosen:
        gates = ",".join(chosen["gates"])
    enabled = parse_passes(passes)
    active, skipped, resolutions = resolve(enabled, parse_gates(gates))
    long = routes.is_long(text)
    if variants > 1 and "plan" not in enabled:
        raise HarnessError("--variants needs pass plan: each variant gets its own plan")
    if variants > 1 and long:
        raise HarnessError("variants of a long text are not supported; rewrite it once, or split it first")
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
        "format": fmt,
        "segments": segments,
        "long": long,
        "variants": [f"v{k}" for k in range(1, variants + 1)] if variants > 1 else [],
        "passes": enabled,
        "preset": preset,
        "gates": active,
        "gates_skipped": skipped,
        "resolutions": resolutions,
        "judge": chosen.get("judge", "self"),
        "max_rounds": max_rounds,
        "rounds": {pid: 0 for pid in enabled},
        "current": enabled[0],
        "unit": 0,
        "done": [],
        "chunk": 0,
        "pairwise_round": 0,
        "return_issues": [],
        "status": "in_progress",
        "frozen": {},
        "history": [],
    }
    if fmt != "text":
        _write_text(session_dir / _source_name(state), source)
        state["source_sha256"] = _sha256(session_dir / _source_name(state))
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


def _keep(session_dir, state):
    """Keep terms from the frozen analysis."""
    return _constraints(frozen_analysis(session_dir, state))[0]


def _masking(original, keep):
    """``(masked text, placeholder mapping)`` of the original with the given keep terms."""
    return protect.protect(original, keep)


def _masked(session_dir, state):
    """``(masked text, placeholder mapping)`` of this session's original."""
    return _masking(_read_text(Path(session_dir) / ORIGINAL_FILE), _keep(session_dir, state))


def _unit(state):
    """The current variant id, or None outside variant sessions."""
    return state["variants"][state["unit"]] if state["variants"] else None


def _units(state):
    """Every variant id, or ``[None]`` for a single rewrite."""
    return state["variants"] or [None]


def _plan(session_dir, state, unit=None):
    """The frozen plan (the variant's own plan in variant sessions), or None."""
    plan = _frozen_json(session_dir, state, "plan")
    if plan is None or not state["variants"]:
        return plan
    return plan["variants"][state["variants"].index(unit)]


def _glossary(session_dir, state):
    """Glossary entries of a long session: from pass 1 if given, else the recurring keep terms."""
    if not state["long"]:
        return None
    analysis = frozen_analysis(session_dir, state)
    if analysis and "glossary" in analysis:
        return analysis["glossary"]
    return routes.default_glossary(_read_text(Path(session_dir) / ORIGINAL_FILE))


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


# --- long sessions: chunks ------------------------------------------------------------------

def _chunks(session_dir, state):
    """``(masked chunks, restored chunks)`` of a long session's original."""
    masked, mapping = _masked(session_dir, state)
    parts = routes.chunks(masked, state["lang"])
    return parts, [protect.restore(p, mapping)[0] for p in parts]


def _sentence_chunks(session_dir, state):
    """Original sentence id → 0-based chunk index."""
    original = _read_text(Path(session_dir) / ORIGINAL_FILE)
    return routes.sentence_chunks(original, _chunks(session_dir, state)[1], state["lang"],
                                  _keep(session_dir, state))


def _chunk_path(session_dir, pid, k, unit=None):
    """Path of chunk ``k`` (0-based) of the text artifact of ``pid``."""
    return Path(session_dir) / _chunk_dir(_artifact(pid, unit)) / f"{k + 1:03d}.md"


def _chunk_input(session_dir, state, pid, k):
    """The file chunk ``k`` of ``pid`` starts from: the previous pass's chunk, or the masked one."""
    previous = _previous_pass(state, pid)
    if previous is None:
        return Path(session_dir) / MASKED_CHUNKS / f"{k + 1:03d}.md"
    return _chunk_path(session_dir, previous, k)


def _write_masked_chunks(session_dir, state):
    """Write the masked chunks the first text pass starts from."""
    folder = Path(session_dir) / MASKED_CHUNKS
    folder.mkdir(exist_ok=True)
    for k, part in enumerate(_chunks(session_dir, state)[0]):
        _write_text(folder / f"{k + 1:03d}.md", part)


def _merged(session_dir, state, pid):
    """The chunk files of ``pid`` merged into one text, or None while one is missing."""
    inputs = _chunks(session_dir, state)[0]
    paths = [_chunk_path(session_dir, pid, k) for k in range(len(inputs))]
    if not all(p.is_file() for p in paths):
        return None
    return routes.merge(inputs, [_read_text(p) for p in paths])


# --- tasks ----------------------------------------------------------------------------------

def _checks(state, pid):
    """What the gate of ``pid`` runs: ``full``, ``floor`` (disabled last gate), or ``skipped``."""
    if BY_ID[pid]["gate"] in state["gates"]:
        return "full"
    return "floor" if pid == state["passes"][-1] else "skipped"


def _references(state, pid):
    """Absolute paths of the reference files this pass needs, and nothing else."""
    names = list(BY_ID[pid]["references"])
    if pid == "plan" and state["variants"]:
        names.append("variants.md")
    if pid in ("lexis", FINAL_PASS):
        names.append(f"languages/{state['lang']}.md")
    if pid == FINAL_PASS and state["persona"]:
        names.append(f"personas/{state['persona']}.md")
    if pid == state["passes"][-1] and _checks(state, pid) == "full":
        names.append("entailment.md")
    if state["format"] != "text" or state["long"] or state["variants"]:
        names.append("routes.md")
    return [str(REFERENCES / n) for n in dict.fromkeys(names) if (REFERENCES / n).is_file()]


def _last_issues(state, pid, unit=None):
    """Open issues from the latest gate result of ``pid`` (empty when it has not failed)."""
    if state["return_issues"]:
        return state["return_issues"]
    for entry in reversed(state["history"]):
        if entry["pass"] == pid and entry.get("unit") == unit and not entry.get("invalidated"):
            return [] if entry["ok"] else entry["issues"]
    return []


def _outputs(session_dir, state):
    """The finished output files, one per variant: the rebuilt file in Files sessions."""
    ext = routes.FILE_EXTENSIONS.get(state["format"], ".txt")
    return [str(Path(session_dir) / _output_name(u, ext)) for u in _units(state)]


def next_task(session_dir):
    """Return the single next task, or a terminal ``done`` / ``incomplete`` step."""
    session_dir = Path(session_dir)
    state = load(session_dir)
    if state["status"] == "complete":
        outputs = _outputs(session_dir, state)
        done = {"step": "done", "status": "complete", "output": outputs[0], "report": str(session_dir / REPORT_FILE)}
        if state["variants"]:
            done["outputs"] = outputs
        return done
    if state["status"] == "incomplete":
        return {"step": "incomplete", "status": "incomplete", "open_issues": open_issues(state)}
    pid = state["current"]
    spec = BY_ID[pid]
    unit = _unit(state) if spec["kind"] == "text" else None
    artifact = _artifact(pid, unit)
    original = _read_text(session_dir / ORIGINAL_FILE)
    analysis = frozen_analysis(session_dir, state)
    keep, ratio = _constraints(analysis)
    task = {
        "step": pid,
        "gate": spec["gate"],
        "checks": _checks(state, pid),
        "pass": f"{state['passes'].index(pid) + 1}/{len(state['passes'])}",
        "inputs": {"original": str(session_dir / ORIGINAL_FILE)},
        "output": str(session_dir / artifact),
        "instructions": _references(state, pid),
        "duties": spec["duties"],
        "constraints": {
            "lang": state["lang"], "mode": state["mode"], "persona": state["persona"],
            "protected": sorted({original[s:e] for s, e, _ in protect.find_spans(original, keep)}),
            "length_ratio": ratio,
        },
        "round": state["rounds"][pid],
        "max_rounds": state["max_rounds"],
        "issues": _last_issues(state, pid, unit),
    }
    if state["format"] != "text":
        task["constraints"]["segments"] = state["segments"]
        task["constraints"]["segment_rule"] = "keep one blank-line separated block per segment, in order"
    if spec["kind"] == "json":
        task["sentences"] = planning.sentences(original, state["lang"], keep)
    if pid == "analysis":
        task["output_format"] = {"facts": [{"id": "f1", "fact": "short claim", "anchors": ["42"]}],
                                 "constraints": {"keep": [], "length_ratio": None},
                                 "discourse": [{"from": 1, "to": 2, "type": "cause"}],
                                 "register": "neutral"}
        if state["long"]:
            task["glossary_candidates"] = glossary.extract(original, keep)
            task["output_format"]["glossary"] = [{"term": "Acme", "decision": "keep", "rendering": None}]
    if pid == "plan":
        row = {"src": [1], "ops": ["lexical"], "target": 1}
        task["output_format"] = {"rows": [row], "axis": None}
        if state["variants"]:
            task["variants"] = len(state["variants"])
            task["output_format"] = {"variants": [{"axis": "structure", "rows": [row]},
                                                  {"axis": "register", "rows": [row]}]}
        if state["long"]:
            of = _sentence_chunks(session_dir, state)
            task["chunks"] = [{"chunk": k + 1, "sentences": [i for i, c in of.items() if c == k]}
                              for k in sorted(set(of.values()))]
    if spec["kind"] == "text":
        _text_task(session_dir, state, pid, unit, task, analysis)
    if analysis:
        task["state"] = {"facts": analysis["facts"], "analysis": analysis}
    return task


def _text_task(session_dir, state, pid, unit, task, analysis):
    """Fill the text-pass fields of ``task``: inputs, ops, plan, placeholders, routes, review."""
    artifact = _artifact(pid, unit)
    ops, duties, merged = responsibilities(state, pid)
    previous = _previous_pass(state, pid)
    masked, mapping = _masked(session_dir, state)
    if previous is None:
        _write_text(session_dir / MASKED_FILE, masked)
        source = session_dir / MASKED_FILE
    else:
        source = session_dir / _artifact(previous, unit)
    task["inputs"]["previous"] = str(source)
    task.update(duties=duties, ops=ops, merged_passes=merged)
    placeholders = [protect.PLACEHOLDER.format(k[1:]) for k in mapping["placeholders"]]
    plan = _plan(session_dir, state, unit)
    if plan:
        task["plan"] = _plan_for(state, pid, plan)
    if state["variants"]:
        task["variant"] = {"id": unit, "index": state["unit"] + 1, "of": len(state["variants"]),
                           "axis": plan["axis"]}
    last = pid == state["passes"][-1]
    final_chunk = True
    if state["long"]:
        if previous is None:
            _write_masked_chunks(session_dir, state)
        n, k = len(_chunks(session_dir, state)[0]), state["chunk"]
        task["constraints"]["glossary"] = _glossary(session_dir, state)
        if k < n:
            chunk_input = _chunk_input(session_dir, state, pid, k)
            task["chunk"] = {"index": k + 1, "of": n}
            task["inputs"]["previous"] = str(chunk_input)
            task["output"] = str(_chunk_path(session_dir, pid, k))
            _chunk_path(session_dir, pid, k).parent.mkdir(exist_ok=True)
            if k:
                task["context"] = {"previous_rewritten": routes.last_paragraph(
                    _read_text(_chunk_path(session_dir, pid, k - 1)))}
            text = _read_text(chunk_input)
            placeholders = [p for p in placeholders if p in text]
            if plan:
                of = _sentence_chunks(session_dir, state)
                task["plan"] = [r for r in task["plan"] if of.get(r["src"][0]) == k]
            final_chunk = k == n - 1
        else:  # fix round after the merged pass failed its gate: edit any chunk file
            task["chunk"] = {"index": None, "of": n, "fix": True}
            task["output"] = str(session_dir / _chunk_dir(artifact))
            task["chunk_files"] = [str(_chunk_path(session_dir, pid, j)) for j in range(n)]
    task["constraints"]["placeholders"] = placeholders
    task["review"] = str(session_dir / _review_name(artifact))
    task["review_format"] = {"accept": [{"id": "w1", "reason": "why the warning is a false positive"}],
                             "verdicts": [{"id": "f1", "verdict": "kept", "note": ""}]}
    if last:
        task["review_required"] = ["verdicts: one per fact in state.facts"] if analysis else []
    if last and task["checks"] == "full" and final_chunk:
        task["review_required"].append(f"{_nli_name(artifact)}: both entailment verdicts for every pair")
        task["entailment"] = {
            "file": str(session_dir / _nli_name(artifact)),
            "basis": "plan" if plan else "aligner",
            "judge_recommended": state["judge"],
            "pairs_command": f"python scripts/pe.py run pairs {session_dir}",
            "format": {"judge": "self", "pairs": [{
                "pair": "r1", "forward": "entail", "backward": "entail",
                "evidence": {"src": "quote from the original", "rew": "quote from the rewrite"},
                "reason": ""}]},
        }


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
    extra = []
    if state["long"] and isinstance(data, dict) and "glossary" in data:
        extra = routes.glossary_errors(data["glossary"])
        data = {k: v for k, v in data.items() if k != "glossary"}
    errors, warnings = planning.validate_analysis(data, original, state["lang"])
    errors += extra
    return {"ok": not errors, "issues": errors, "advisory": {"warnings": warnings}}


def _gate_plan(session_dir, state, original):
    """Gate 2: every sentence covered exactly once with known ops and consistent targets."""
    data, problem = _read_json_artifact(session_dir, "plan")
    if problem:
        return {"ok": False, "issues": [problem], "advisory": {}}
    analysis = frozen_analysis(session_dir, state)

    def one(plan):
        """Validate one plan against the original."""
        return planning.validate_plan(plan, original, state["lang"], state["mode"], analysis)

    if state["variants"]:
        errors, warnings = routes.validate_variants(data, len(state["variants"]), one)
    else:
        errors, warnings = one(data)
        if state["long"] and not errors:
            errors = routes.plan_chunk_errors(data, _sentence_chunks(session_dir, state))
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


def restored_text(session_dir, state, pid, unit=None, masked_text=None):
    """``(restored text, placeholder issues)`` of the text artifact of ``pid`` (or ``masked_text``)."""
    if masked_text is None:
        masked_text = _read_text(Path(session_dir) / _artifact(pid, unit))
    restored, report = protect.restore(masked_text, _masked(session_dir, state)[1])
    return restored, report["issues"]


def _entailment_pairs(session_dir, state, unit, original, rewrite, warnings):
    """``(pairs, basis)`` of a rewrite, flagged with ``warnings``."""
    plan = _plan(session_dir, state, unit)
    found, basis = entailment.pairs(original, rewrite, state["lang"], _keep(session_dir, state), plan,
                                    state["mode"])
    return (None if found is None else entailment.flag(found, warnings)), basis


def entailment_pairs(session_dir):
    """The pairs the agent must judge for the current rewrite of the last text pass."""
    session_dir = Path(session_dir)
    state = load(session_dir)
    last = state["passes"][-1]
    if state["status"] != "in_progress" or state["current"] != last:
        raise HarnessError(f"pairs are judged at the last pass ({last}); the session is at "
                           f"{state['current'] or state['status']}")
    unit = _unit(state)
    artifact = _artifact(last, unit)
    if state["long"]:
        masked_text = _merged(session_dir, state, last)
        if masked_text is None:
            raise HarnessError("write every chunk file of this pass first: pairs come from the whole rewrite")
    elif (session_dir / artifact).is_file():
        masked_text = _read_text(session_dir / artifact)
    else:
        raise HarnessError(f"write {artifact} first: pairs come from the rewrite")
    original = _read_text(session_dir / ORIGINAL_FILE)
    rewrite = restored_text(session_dir, state, last, unit, masked_text)[0]
    chk = check.check(original, rewrite, lang_code=state["lang"], keep=_keep(session_dir, state))
    found, basis = _entailment_pairs(session_dir, state, unit, original, rewrite, chk["warnings"])
    if found is None:
        raise HarnessError("the rewrite has more sentences than the plan rows can hold; "
                           "submit it to see the plan issues")
    result = {"ok": True, "pass": last, "file": str(session_dir / _nli_name(artifact)), "basis": basis,
              "pairs": [{k: p[k] for k in ("pair", "src", "original", "rewritten", "may_drop", "flags")}
                        for p in found]}
    if unit:
        result["variant"] = unit
    return result


def _gate_entailment(session_dir, state, pid, unit, original, rewrite, chk):
    """``(issues, summary)`` of the entailment verdicts for the last text pass."""
    found, basis = _entailment_pairs(session_dir, state, unit, original, rewrite,
                                      chk["warnings"] + chk["accepted"])
    if found is None:
        return [], None  # the plan check already reports the sentence count
    summary = {"basis": basis, "pairs": len(found), "judge": None}
    if not found:
        return [], summary
    path = Path(session_dir) / _nli_name(_artifact(pid, unit))
    if not path.is_file():
        return [_issue("nli_file_missing", file=path.name, pairs=[p["pair"] for p in found])], summary
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as e:
        return [_issue("invalid_nli", error=f"{path.name} is not valid JSON: {e}")], summary
    errors, summary["judge"] = entailment.validate(data, found)
    return errors, summary


def _gate_text(session_dir, state, original, pid, unit=None, floor=False):
    """Gates 3–5: ``pe check`` against the original, plan adherence, sentence count, facts.

    With ``floor`` only the checks that cannot be disabled run: ``pe check`` errors (numbers,
    citations, protected spans, placeholders), one block per segment in Files sessions, and,
    after pass 1, fact anchors and verdicts.
    """
    artifact = _artifact(pid, unit)
    try:
        review = _read_review(session_dir, artifact)
        accept = review.get("accept", [])
        if not isinstance(accept, list):
            raise facts.FactsError("'accept' must be a list of {id, reason}")
        verdicts = facts.parse_verdicts(review["verdicts"]) if "verdicts" in review else None
    except facts.FactsError as e:
        return {"ok": False, "issues": [_issue("invalid_review", error=str(e))], "advisory": {}}

    analysis = frozen_analysis(session_dir, state)
    plan = _plan(session_dir, state, unit)
    keep, ratio = _constraints(analysis)
    last = pid == state["passes"][-1]
    ops = set(responsibilities(state, pid)[0])
    rewrite, issues = restored_text(session_dir, state, pid, unit)
    if state["format"] != "text":
        issues += routes.segment_issues(rewrite, state["segments"])

    chk = check.check(original, rewrite, lang_code=state["lang"], keep=keep, accept=accept)
    if floor:
        issues += chk["errors"]
        return _with_facts(session_dir, state, original, rewrite, verdicts or {}, issues,
                           {"accepted": [], "advisory": {"warnings": chk["warnings"]}, "floor": True})
    issues += chk["errors"] + chk["warnings"]
    issues += [_issue("rejected_accept", **r) for r in chk["rejected_accepts"]]

    if plan and (ops & STRUCTURE_OPS or last):
        # The pass that owns structure, and the last pass, must match the plan's sentence map.
        drops_done = "shorten" in ops or _drops_done_before(state, pid)
        issues += planning.adherence(plan, original, rewrite, state["lang"], keep, drops_done)
    elif not ops & COUNT_CHANGING_OPS and _previous_pass(state, pid):
        before = restored_text(session_dir, state, _previous_pass(state, pid), unit)[0]
        counts = [len(planning.sentences(t, state["lang"], keep)) for t in (before, rewrite)]
        if counts[0] != counts[1]:
            issues.append(_issue("sentence_count_changed", expected=counts[0], got=counts[1]))

    # An explicit length target is enforced at the last text gate; bands stay advisory.
    cmp = metrics.compare(original, rewrite, lang_code=state["lang"], mode=state["mode"],
                          target_ratio=ratio if last else None)
    if not cmp["ok"]:
        issues.append(_issue("length_target", **cmp["target"], length_ratio=cmp["length_ratio"]))
    result = {"accepted": chk["accepted"], "advisory": {"metrics": cmp, "unsupported": chk["unsupported"]}}
    if last:
        nli_issues, result["entailment"] = _gate_entailment(session_dir, state, pid, unit, original, rewrite, chk)
        issues += nli_issues
        if state["long"]:
            issues += routes.glossary_issues(original, rewrite, _glossary(session_dir, state))
    # Anchors are checked at every text gate; verdicts are required at the last one.
    return _with_facts(session_dir, state, original, rewrite, (verdicts or {}) if last else verdicts,
                       issues, result)


def _with_facts(session_dir, state, original, rewrite, verdicts, issues, result):
    """Add the frozen fact checks (when pass 1 ran) to a text gate result and finish it."""
    analysis = frozen_analysis(session_dir, state)
    if analysis:
        report = facts.verify(original, analysis["facts"], rewrite, verdicts, lang_code=state["lang"])
        issues += report["errors"]
        result["advisory"]["facts"] = report["warnings"]
    result.update(ok=not issues, issues=issues)
    return result


def run_gate(session_dir, state, pid, unit=None):
    """Run the gate of pass ``pid`` (for variant ``unit``) against the original."""
    original = _read_text(Path(session_dir) / ORIGINAL_FILE)
    if pid == "analysis":
        return _gate_analysis(session_dir, state, original)
    if pid == "plan":
        return _gate_plan(session_dir, state, original)
    checks = _checks(state, pid)
    if checks == "skipped":
        return {"ok": True, "issues": [], "skipped": True}
    return _gate_text(session_dir, state, original, pid, unit, floor=checks == "floor")


def _record(session_dir, state, entry):
    """Append a gate entry to the history and write it to the gates folder."""
    unit = f"-{entry['unit']}" if entry.get("unit") else ""
    _write_json(Path(session_dir) / GATES_DIR / f"{entry['gate']}-{entry['pass']}{unit}-r{entry['round']}.json",
                entry)
    state["history"].append(entry)


def submit(session_dir):
    """Gate the current pass's artifact, record the result, then advance, retry, or stop.

    In long sessions each chunk is submitted on its own; the gate runs once every chunk file of
    the pass exists, on the merged text.
    """
    session_dir = Path(session_dir)
    state = load(session_dir)
    if state["status"] != "in_progress":
        raise HarnessError(f"session is {state['status']}; nothing to submit")
    pid = state["current"]
    spec = BY_ID[pid]
    unit = _unit(state) if spec["kind"] == "text" else None
    artifact = session_dir / _artifact(pid, unit)
    if spec["kind"] == "text" and state["long"]:
        n, k = len(_chunks(session_dir, state)[0]), state["chunk"]
        if k < n:
            path = _chunk_path(session_dir, pid, k)
            if not path.is_file():
                raise HarnessError(f"expected chunk file is missing: {path}")
            state["chunk"] += 1
            if state["chunk"] < n:
                save(session_dir, state)
                return {"ok": True, "pass": pid, "gate": spec["gate"], "chunk": f"{k + 1}/{n}",
                        "round": state["rounds"][pid], "status": state["status"], "next": pid, "issues": []}
        merged = _merged(session_dir, state, pid)
        if merged is None:
            raise HarnessError(f"a chunk file of {pid} is missing in {_chunk_dir(artifact.name)}")
        _write_text(artifact, merged)
    if not artifact.is_file():
        raise HarnessError(f"expected artifact is missing: {artifact}")

    state["return_issues"] = []
    result = run_gate(session_dir, state, pid, unit)
    entry = {"pass": pid, "gate": spec["gate"], "round": state["rounds"][pid], "ok": result["ok"],
             "issues": result["issues"], "accepted": result.get("accepted", []),
             "advisory": result.get("advisory", {})}
    if unit:
        entry["unit"] = unit
    if result.get("entailment"):
        entry["entailment"] = result["entailment"]
    if result.get("skipped") or result.get("floor"):
        entry["checks"] = "skipped" if result.get("skipped") else "floor"
    _record(session_dir, state, entry)

    if result["ok"]:
        if spec["kind"] == "json":
            state["frozen"][pid] = _sha256(artifact)
        _advance(session_dir, state, pid, unit)
    elif state["rounds"][pid] >= state["max_rounds"]:
        state["status"] = "incomplete"
    else:
        state["rounds"][pid] += 1
    save(session_dir, state)
    if state["status"] != "in_progress":
        write_report(session_dir, state)
    out = {"ok": result["ok"], "pass": pid, "gate": spec["gate"], "round": entry["round"],
           "status": state["status"], "next": state["current"], "issues": result["issues"]}
    if unit:
        out.update(variant=unit, next_variant=_unit(state) if state["current"] else None)
    if state["return_issues"]:
        out["pairwise"] = state["return_issues"]
    return out


def _advance(session_dir, state, pid, unit):
    """Move on after a passed gate: next variant, next pass, the pairwise gate, or done."""
    if unit is not None:
        if unit not in state["done"]:
            state["done"].append(unit)
        remaining = [u for u in state["variants"] if u not in state["done"]]
        if remaining:
            state["unit"], state["rounds"][pid], state["chunk"] = state["variants"].index(remaining[0]), 0, 0
            return
    if pid != state["passes"][-1]:
        state["current"] = state["passes"][state["passes"].index(pid) + 1]
        state["unit"], state["done"], state["chunk"] = 0, [], 0
        return
    if state["variants"] and _checks(state, pid) == "full" and not _gate_pairwise(session_dir, state, pid):
        return
    state["current"], state["status"] = None, "complete"
    _finish(session_dir, state, pid)


def _gate_pairwise(session_dir, state, pid):
    """Variant gate: every pair of finished variants must differ; send the later one back if not."""
    texts = [restored_text(session_dir, state, pid, u)[0] for u in state["variants"]]
    pairs = metrics.pairwise(texts, lang_code=state["lang"])
    issues = routes.pairwise_issues(pairs, state["variants"])
    _record(session_dir, state, {"pass": "variants", "gate": PAIRWISE_GATE, "round": state["pairwise_round"],
                                 "ok": not issues, "issues": issues, "accepted": [],
                                 "advisory": {"pairs": pairs["pairs"]}})
    if not issues:
        return True
    if state["pairwise_round"] >= state["max_rounds"]:
        state["status"] = "incomplete"
        return False
    state["pairwise_round"] += 1
    target = issues[0]["variants"][1]
    state["done"].remove(target)
    state["unit"], state["rounds"][pid], state["return_issues"] = state["variants"].index(target), 0, issues
    return False


def _finish(session_dir, state, pid):
    """Write the restored outputs (and the rebuilt files in Files sessions)."""
    session_dir = Path(session_dir)
    for unit in _units(state):
        text = restored_text(session_dir, state, pid, unit)[0]
        _write_text(session_dir / _output_name(unit), text)
        if state["format"] != "text":
            source = _read_text(session_dir / _source_name(state))
            rebuilt = routes.rebuild_file(source, state["format"], text)
            _write_text(session_dir / _output_name(unit, routes.FILE_EXTENSIONS[state["format"]]), rebuilt)


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
        for unit in (_units(state) if BY_ID[pid]["kind"] == "text" else [None]):
            artifact = _artifact(pid, unit)
            for name in (artifact, _review_name(artifact), _nli_name(artifact)):
                if (session_dir / name).is_file():
                    (session_dir / name).unlink()
            shutil.rmtree(session_dir / _chunk_dir(artifact), ignore_errors=True)
        state["rounds"][pid] = 0
        state["frozen"].pop(pid, None)
    for entry in state["history"]:
        if entry["pass"] in dropped or entry["pass"] == "variants":
            entry["invalidated"] = True
    state.update(current=to, status="in_progress", unit=0, done=[], chunk=0, pairwise_round=0, return_issues=[])
    for path in [session_dir / REPORT_FILE, session_dir / MASKED_FILE, *session_dir.glob("output*")]:
        if path.is_file():
            path.unlink()
    shutil.rmtree(session_dir / MASKED_CHUNKS, ignore_errors=True)
    save(session_dir, state)
    return {"ok": True, "current": to, "invalidated": dropped}


def open_issues(state):
    """Issues of the latest failed gate that was never passed afterwards."""
    latest = {}
    for entry in state["history"]:
        if not entry.get("invalidated"):
            latest[(entry["pass"], entry.get("unit"))] = entry
    return [dict(issue, gate=e["gate"], **{"pass": e["pass"]}, **({"variant": e["unit"]} if e.get("unit") else {}))
            for e in latest.values() if not e["ok"] for issue in e["issues"]]


def status(session_dir):
    """Current step, rounds used, and the gate history."""
    state = load(session_dir)
    return {"status": state["status"], "current": state["current"], "passes": state["passes"],
            "gates": state["gates"], "resolutions": state["resolutions"], "rounds": state["rounds"],
            "max_rounds": state["max_rounds"], "variant": _unit(state) if state["current"] else None,
            "chunk": state["chunk"] if state["long"] else None,
            "frozen": [BY_ID[pid]["artifact"] for pid in state["frozen"]],
            "history": [dict({k: e[k] for k in ("pass", "gate", "round", "ok")},
                             invalidated=e.get("invalidated", False)) for e in state["history"]]}


def build_report(session_dir, state):
    """The session report: what ran, what was skipped, what is still open."""
    session_dir = Path(session_dir)
    live = [e for e in state["history"] if not e.get("invalidated")]
    complete = state["status"] == "complete"
    outputs = _outputs(session_dir, state) if complete else []
    report = {
        "status": state["status"],
        "lang": state["lang"], "mode": state["mode"], "persona": state["persona"],
        "format": state["format"], "long": state["long"],
        "passes_run": list(dict.fromkeys(e["pass"] for e in live if e["ok"] and e["pass"] in BY_ID)),
        "preset": state["preset"],
        "gates_run": [{"gate": "floor" if e.get("checks") == "floor" else e["gate"], "pass": e["pass"],
                       "round": e["round"], "ok": e["ok"], **({"variant": e["unit"]} if e.get("unit") else {})}
                      for e in live if e.get("checks") != "skipped"],
        "gates_skipped": state["gates_skipped"],
        "resolutions": state["resolutions"],
        "skipped_checks": skipped_checks(state),
        "open_issues": open_issues(state),
        "accepted_warnings": [a for e in live if e["ok"] for a in e["accepted"]],
        "facts_frozen": "analysis" in state["frozen"],
        "facts": _facts_report(session_dir, state),
        "entailment": _entailment_report(state, live),
        "output": outputs[0] if outputs else None,
    }
    if state["variants"]:
        plan = _frozen_json(session_dir, state, "plan") or {"variants": [{}] * len(state["variants"])}
        report["variants"] = [{"variant": u, "axis": p.get("axis"), "output": outputs[k] if outputs else None}
                              for k, (u, p) in enumerate(zip(state["variants"], plan["variants"]))]
    return report


def _facts_report(session_dir, state):
    """Fact verdict counts from the last pass's review files, or None without pass 1."""
    analysis = frozen_analysis(session_dir, state)
    if not analysis:
        return None
    counts = {"total": len(analysis["facts"]), "kept": 0, "changed": [], "lost": [], "unjudged": []}
    for unit in _units(state):
        try:
            review = _read_review(session_dir, _artifact(state["passes"][-1], unit))
            verdicts = facts.parse_verdicts(review.get("verdicts", []))
        except facts.FactsError:
            verdicts = {}
        for fact in analysis["facts"]:
            verdict = verdicts.get(fact["id"], {}).get("verdict")
            if verdict == "kept":
                counts["kept"] += 1
            else:
                counts[verdict if verdict in ("changed", "lost") else "unjudged"].append(
                    dict({"id": fact["id"]}, **({"variant": unit} if unit else {})))
    if state["variants"]:
        counts["total"] *= len(state["variants"])
    return counts


def _entailment_report(state, live):
    """Entailment summary of the latest passed gate that judged pairs (summed over variants)."""
    latest = {}
    for e in live:
        if e["ok"] and e.get("entailment"):
            latest[e.get("unit")] = e["entailment"]
    if not latest:
        return None
    judges = {s["judge"] for s in latest.values() if s["judge"]}
    summary = dict(next(reversed(latest.values())))
    if state["variants"]:
        summary["pairs"] = sum(s["pairs"] for s in latest.values())
        summary["judge"] = judges.pop() if len(judges) == 1 else ("mixed" if judges else None)
    # The harness cannot see who judged: "independent" is the agent's claim.
    return dict(summary, judge_verified=False)


def write_report(session_dir, state=None):
    """Write ``report.json`` and return the report."""
    state = load(session_dir) if state is None else state
    report = build_report(session_dir, state)
    _write_json(Path(session_dir) / REPORT_FILE, report)
    return report
