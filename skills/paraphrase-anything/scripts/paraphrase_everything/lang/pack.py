"""The language-pack contract: schema, fixtures, coverage tiers, and scaffolding (story 012).

A pack is ``lang/<code>.json`` plus ``references/languages/<code>.md``. Tiers:

- 0: generic fallback only (no pack, or a pack that fails its schema or fixtures);
- 1: data-only pack whose schema and fixtures pass, with a language note;
- 2: tier 1 plus at least ``EVAL_CASES_FOR_TIER_2`` eval cases in ``evals/cases/<code>/``.

Fixtures live in the pack itself, so registering a language never touches Python code.
"""

import json
import re
from pathlib import Path

from . import DEFAULT, LANG_DIR, available, detect, load
from ..text import count, markers_pattern, split_sentences

SKILL_DIR = LANG_DIR.parents[2]
REPO_EVALS = SKILL_DIR.parents[1] / "evals" / "cases"
EVAL_CASES_FOR_TIER_2 = 10
CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")

_LIST = "list"
SCHEMA = {
    "code": str, "name": str, "length_unit": ("word", "char"), "match": ("word", "substring"),
    "has_case": bool, "detect_words": _LIST, "sentence_terminators": _LIST, "abbreviations": _LIST,
    "negation_markers": _LIST, "hedge_markers": _LIST, "decimal_separator": str,
    "thousands_separator": str, "cliches": _LIST, "subtitle": dict, "detect": dict, "fixtures": dict,
}
OPTIONAL = {"subtitle", "fixtures"}
DETECT_KEYS = {"script": str, "priority": int, "min_share": (int, float), "latin_fallback": bool}
FIXTURE_KEYS = ("detect", "sentences", "negation", "hedge")


def _paths(code, skill_dir):
    """Where the pack data and the language note of ``code`` live under ``skill_dir``."""
    skill_dir = Path(skill_dir)
    return (skill_dir / "scripts" / "paraphrase_everything" / "lang" / f"{code}.json",
            skill_dir / "references" / "languages" / f"{code}.md")


def validate(data, code):
    """Return schema problems of raw pack ``data`` (before defaults are merged)."""
    problems = []
    for key, kind in SCHEMA.items():
        if key not in data:
            if key not in OPTIONAL:
                problems.append(f"missing key: {key}")
            continue
        value = data[key]
        if kind == _LIST:
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                problems.append(f"{key}: must be a list of non-empty strings")
        elif isinstance(kind, tuple):
            if value not in kind:
                problems.append(f"{key}: must be one of {', '.join(kind)}")
        elif not isinstance(value, kind):
            problems.append(f"{key}: must be a {kind.__name__}")
    problems += [f"unknown key: {key}" for key in sorted(set(data) - set(SCHEMA))]
    if data.get("code") != code:
        problems.append(f"code: must be {code!r} (the file name)")
    if not data.get("sentence_terminators"):
        problems.append("sentence_terminators: must not be empty")
    if data.get("decimal_separator") == data.get("thousands_separator"):
        problems.append("decimal_separator and thousands_separator must differ")
    rule = data.get("detect")
    if isinstance(rule, dict):
        for key, value in rule.items():
            kind = DETECT_KEYS.get(key)
            if kind is None:
                problems.append(f"detect: unknown key {key}")
            elif not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
                problems.append(f"detect.{key}: wrong type")
        if isinstance(rule.get("script"), str):
            try:
                re.compile(rule["script"])
            except re.error as e:
                problems.append(f"detect.script: invalid regex ({e})")
    problems += _fixture_problems(data.get("fixtures", {}))
    return problems


def _fixture_problems(fixtures):
    """Shape problems of a ``fixtures`` block."""
    if not isinstance(fixtures, dict):
        return []  # already reported by the schema check
    problems = [f"fixtures: unknown key {key}" for key in sorted(set(fixtures) - set(FIXTURE_KEYS))]
    for key in ("detect", "negation", "hedge"):
        value = fixtures.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            problems.append(f"fixtures.{key}: must be a list of non-empty strings")
    for case in fixtures.get("sentences", []):
        if not (isinstance(case, dict) and isinstance(case.get("text"), str)
                and isinstance(case.get("count"), int)):
            problems.append("fixtures.sentences: each item must be {\"text\": str, \"count\": int}")
            break
    return problems


def run_fixtures(code, data=None):
    """Run the fixtures of pack ``code`` (installed data unless ``data`` is given); return failures."""
    data = load(code) if data is None else dict(load(DEFAULT), **data)
    fixtures = data.get("fixtures") or {}
    failures = []
    if not fixtures.get("detect"):
        failures.append("fixtures.detect: add at least one sample text")
    if not fixtures.get("sentences"):
        failures.append("fixtures.sentences: add at least one {text, count} case")
    for sample in fixtures.get("detect", []):
        got = detect(sample)
        if got != code:
            failures.append(f"detect: {sample!r} detected as {got}")
    for case in fixtures.get("sentences", []):
        got = len(split_sentences(case["text"], data))
        if got != case["count"]:
            failures.append(f"sentences: {case['text']!r} splits into {got}, expected {case['count']}")
    word_bounded = data["match"] == "word"
    for kind in ("negation", "hedge"):
        markers = data[f"{kind}_markers"]
        samples = fixtures.get(kind, [])
        if markers and not samples:
            failures.append(f"fixtures.{kind}: add a sample for the {kind} markers")
        pattern = markers_pattern(markers, word_bounded)
        for sample in samples:
            if not count(pattern, sample):
                failures.append(f"{kind}: no marker found in {sample!r}")
    return failures


def _eval_cases(code, evals_dir):
    """Number of eval case files for ``code``, or None when the eval set is not present."""
    evals_dir = Path(evals_dir)
    if not evals_dir.is_dir():
        return None
    return len(list((evals_dir / code).glob("*.json")))


def coverage(code, evals_dir=REPO_EVALS):
    """Tier, supported checks, and open problems of installed pack ``code``."""
    data_path, note_path = _paths(code, SKILL_DIR)
    raw = json.loads(data_path.read_text(encoding="utf-8"))
    problems = validate(raw, code) or run_fixtures(code)
    if not note_path.exists():
        problems.append(f"missing language note: references/languages/{code}.md")
    data = load(code)
    cases = _eval_cases(code, evals_dir)
    tier = 0 if problems else 2 if cases and cases >= EVAL_CASES_FOR_TIER_2 else 1
    return {
        "code": code,
        "name": data["name"],
        "tier": tier,
        "length_unit": data["length_unit"],
        "checks": {"negation": bool(data["negation_markers"]), "hedge": bool(data["hedge_markers"]),
                   "proper_noun": data["has_case"], "detect": bool(data["detect"] or data["detect_words"])},
        "eval_cases": cases,
        "problems": problems,
    }


def coverage_table(evals_dir=REPO_EVALS):
    """Coverage of every installed pack."""
    return [coverage(code, evals_dir) for code in available()]


NOTE_TEMPLATE = """# {name} notes

- **Table headers:** Original · Rewritten · Change
- **Register:** TODO: formal and casual forms, honorifics, how to keep one register throughout.
- **Pronouns and address:** TODO: forms of "you" and how to keep them consistent.
- **Length unit:** `pe metrics` counts {unit}s for {name}.
- **Hedges:** TODO: words that carry certainty; keep the same strength.
- **Negation:** TODO: negation forms and double negatives that `pe check` will warn about.
- **Numbers:** TODO: separators and numeral systems.
- **Clichés to avoid:** TODO.
"""


def scaffold(code, name, skill_dir=SKILL_DIR, length_unit="word"):
    """Create a tier-0 pack for ``code`` (data file and language note); return the created paths.

    Raises ``ValueError`` for an invalid code or unit and ``FileExistsError`` if a file exists.
    """
    if not CODE_RE.match(code) or code == DEFAULT:
        raise ValueError(f"invalid language code: {code!r} (use e.g. 'ko' or 'pt-br')")
    if length_unit not in SCHEMA["length_unit"]:
        raise ValueError(f"length unit must be one of {', '.join(SCHEMA['length_unit'])}")
    data_path, note_path = _paths(code, skill_dir)
    for path in (data_path, note_path):
        if path.exists():
            raise FileExistsError(f"already exists: {path}")
    char = length_unit == "char"
    data = {
        "code": code, "name": name, "length_unit": length_unit,
        "match": "substring" if char else "word", "has_case": not char,
        "detect_words": [], "sentence_terminators": [".", "!", "?"], "abbreviations": [],
        "negation_markers": [], "hedge_markers": [], "decimal_separator": ".",
        "thousands_separator": ",", "cliches": [], "detect": {},
        "fixtures": {key: [] for key in FIXTURE_KEYS},
    }
    data_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    note_path.write_text(NOTE_TEMPLATE.format(name=name, unit=length_unit), encoding="utf-8", newline="")
    return [str(data_path), str(note_path)]
