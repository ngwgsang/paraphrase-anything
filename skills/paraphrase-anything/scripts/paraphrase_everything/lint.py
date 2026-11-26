"""Readability and repetition lint for a rewrite (story 005).

Points at specific spots (clichés, repeated or added connectors, dense dashes, monotonous
sentence length) so the agent revises those spots instead of regenerating everything. Rules are
data: ``lint.json`` holds the defaults, extra rule files can add or override rules by ``id``, and
phrase lists come from the language data. Findings are ``warn`` or ``info``; lint never fails a run.
This is a readability aid, not "AI-sounding" detection.
"""

import json
import statistics
from pathlib import Path

from . import lang, metrics
from .check import Doc
from .text import markers_pattern

RULES_FILE = Path(__file__).with_name("lint.json")
SEVERITIES = ("warn", "info")
KINDS = ("phrases", "repeat", "added", "density", "uniformity")
NEEDS_ORIGINAL = ("added",)


class LintError(ValueError):
    """Raised when a rule file is malformed."""


def _read_rules(path):
    """The ``rules`` list of one rule file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LintError(f"{Path(path).name} is not valid JSON: {e}") from None
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise LintError(f"{Path(path).name} must be an object with a 'rules' list")
    return data["rules"]


def _validate(rule, source):
    """Raise ``LintError`` when ``rule`` (from file ``source``) is malformed."""
    if not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"]:
        raise LintError(f"{source}: every rule needs a string id")
    if rule.get("enabled") is False:
        return
    where = f"{source}: rule {rule['id']}"
    if rule.get("kind") not in KINDS:
        raise LintError(f"{where}: kind must be one of {', '.join(KINDS)}")
    if rule.get("severity") not in SEVERITIES:
        raise LintError(f"{where}: severity must be one of {', '.join(SEVERITIES)}")
    if rule["kind"] in ("phrases", "repeat", "added") and not ("source" in rule or "phrases" in rule):
        raise LintError(f"{where}: needs 'source' (a language data key) or 'phrases'")
    if rule["kind"] == "density" and not rule.get("chars"):
        raise LintError(f"{where}: needs 'chars'")


def load_rules(extra_dir=None):
    """Default rules, then every ``*.json`` in ``extra_dir`` in name order; a same ``id`` replaces.

    A rule with ``"enabled": false`` turns that id off.
    """
    by_id = {}
    files = [RULES_FILE] + (sorted(Path(extra_dir).glob("*.json")) if extra_dir else [])
    if extra_dir and not Path(extra_dir).is_dir():
        raise LintError(f"rules directory not found: {extra_dir}")
    for path in files:
        for rule in _read_rules(path):
            _validate(rule, Path(path).name)
            by_id[rule["id"]] = rule
    return [r for r in by_id.values() if r.get("enabled") is not False]


def _phrases(rule, data, code):
    """The phrase list of a rule: a language data key, an inline list, or a per-language map."""
    if "source" in rule:
        return list(data.get(rule["source"], []))
    phrases = rule["phrases"]
    return list(phrases.get(code, [])) if isinstance(phrases, dict) else list(phrases)


def _pattern(phrases, data):
    """One regex for ``phrases``, word-bounded when the language matches whole words."""
    return markers_pattern(phrases, data["match"] == "word")


def _key(text):
    """Case-folded match text, so "However" and "however" count as one connector."""
    return " ".join(text.lower().split())


class _Text:
    """A text analysed once for lint: opaque spans blanked, sentences split."""

    def __init__(self, raw, data):
        """Analyse ``raw`` with the language ``data``."""
        doc = Doc(raw, data, ())
        self.raw, self.prose, self.spans = raw, doc.prose, doc.spans

    def sentence_of(self, pos):
        """Index of the sentence containing offset ``pos``."""
        for i, (s, e) in enumerate(self.spans):
            if s <= pos < e:
                return i
        return len(self.spans)

    def matches(self, pattern):
        """Matches of ``pattern`` in the prose (offsets are valid on the raw text)."""
        return list(pattern.finditer(self.prose)) if pattern else []


def _finding(rule, start, end, raw, **extra):
    """One finding: rule id, severity, span offsets, the matched text, and the hint."""
    return dict({"rule": rule["id"], "severity": rule["severity"], "start": start, "end": end,
                 "text": raw[start:end], "hint": rule.get("hint", "")}, **extra)


def _rule_phrases(rule, text, original, pattern):
    """Each phrase the rewrite uses but the original does not (all of them without an original)."""
    used = {_key(m.group(0)) for m in original.matches(pattern)} if original else set()
    return [_finding(rule, m.start(), m.end(), text.raw) for m in text.matches(pattern)
            if _key(m.group(0)) not in used]


def _rule_repeat(rule, text, original, pattern):
    """A phrase repeated within ``window`` sentences of its previous use."""
    window, last, found = rule.get("window", 3), {}, []
    for m in text.matches(pattern):
        key, at = _key(m.group(0)), text.sentence_of(m.start())
        if key in last and at - last[key] < window:
            found.append(_finding(rule, m.start(), m.end(), text.raw, sentences_apart=at - last[key]))
        last[key] = at
    return found


def _rule_added(rule, text, original, pattern):
    """Uses of a phrase beyond the number of times the original uses it."""
    allowed = {}
    for m in original.matches(pattern):
        allowed[_key(m.group(0))] = allowed.get(_key(m.group(0)), 0) + 1
    seen, found = {}, []
    for m in text.matches(pattern):
        key = _key(m.group(0))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > allowed.get(key, 0):
            found.append(_finding(rule, m.start(), m.end(), text.raw, original_count=allowed.get(key, 0)))
    return found


def _rule_density(rule, text):
    """Every listed character when there are too many of them per sentence."""
    spots = [i for i, ch in enumerate(text.prose) if any(text.prose.startswith(c, i) for c in rule["chars"])]
    sentences = max(len(text.spans), 1)
    if len(spots) < rule.get("min_count", 2) or len(spots) / sentences <= rule.get("max_per_sentence", 0.34):
        return []
    found = []
    for i in spots:
        char = next(c for c in sorted(rule["chars"], key=len, reverse=True) if text.prose.startswith(c, i))
        if not found or i >= found[-1]["end"]:
            found.append(_finding(rule, i, i + len(char), text.raw, count=len(spots), sentences=sentences))
    return found


def _rule_uniformity(rule, text, data):
    """One finding over the whole text when sentence lengths barely vary."""
    lengths = [len(metrics.tokens(text.prose[s:e], data)) for s, e in text.spans]
    lengths = [n for n in lengths if n]
    if len(lengths) < rule.get("min_sentences", 4):
        return []
    cv = statistics.pstdev(lengths) / statistics.mean(lengths)
    if cv >= rule.get("min_cv", 0.15):
        return []
    return [_finding(rule, text.spans[0][0], text.spans[-1][1], text.raw,
                     lengths=lengths, cv=round(cv, 3))]


PHRASE_RULES = {"phrases": _rule_phrases, "repeat": _rule_repeat, "added": _rule_added}


def lint(rewrite, original=None, lang_code="auto", rules=None):
    """Lint ``rewrite``; with ``original``, phrase rules flag only what the rewrite introduced.

    Returns ``{ok, lang, findings, counts, rules_run, skipped}``; ``ok`` is always True.
    """
    code = lang.detect(original or rewrite) if lang_code == "auto" else lang_code
    data = lang.load(code)
    rules = load_rules() if rules is None else rules
    text = _Text(rewrite, data)
    source = _Text(original, data) if original is not None else None
    findings, run, skipped = [], [], []
    for rule in rules:
        kind = rule["kind"]
        if kind in NEEDS_ORIGINAL and source is None:
            skipped.append({"rule": rule["id"], "why": "needs the original (--original)"})
            continue
        if kind == "uniformity":
            found = _rule_uniformity(rule, text, data)
        elif kind == "density":
            found = _rule_density(rule, text)
        else:
            pattern = _pattern(_phrases(rule, data, code), data)
            if pattern is None:
                skipped.append({"rule": rule["id"], "why": f"no phrases for language {code}"})
                continue
            found = PHRASE_RULES[kind](rule, text, source, pattern)
        run.append(rule["id"])
        findings += found
    findings.sort(key=lambda f: (f["start"], f["rule"]))
    for n, f in enumerate(findings, 1):
        f["id"] = f"l{n}"
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
    return {"ok": True, "lang": code, "findings": findings, "counts": counts, "rules_run": run, "skipped": skipped}
