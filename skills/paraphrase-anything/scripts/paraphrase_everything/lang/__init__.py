"""Language data loader and detector.

All language-specific literals live in ``<code>.json`` next to this file, including how to
detect the language (``detect``). Code must never hard-code them (story 012).
"""

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

LANG_DIR = Path(__file__).parent
DEFAULT = "default"

_LETTER = re.compile(r"[^\W\d_]")
# Latin script (basic, Latin-1, Extended-A/B, Extended Additional); a script range, not a language.
_LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ɏḀ-ỿ]")
_WORD = re.compile(r"[^\W\d_]+")


def available(lang_dir=LANG_DIR):
    """Codes of all installed languages, excluding the generic fallback."""
    return sorted(p.stem for p in Path(lang_dir).glob("*.json") if p.stem != DEFAULT)


@lru_cache(maxsize=None)
def _read(code):
    """Read and cache one language JSON file."""
    with open(LANG_DIR / f"{code}.json", encoding="utf-8") as f:
        return json.load(f)


def load(code):
    """Return language data for ``code``, filled in with generic defaults.

    Unknown codes return the generic fallback with ``supported`` set to False,
    so callers can report dependent checks as ``unsupported``.
    """
    data = dict(_read(DEFAULT))
    supported = code in available()
    if supported:
        data.update(_read(code))
    data["supported"] = supported
    return data


@lru_cache(maxsize=None)
def _detectors():
    """Script detectors from every pack's ``detect`` block, highest priority first."""
    found = []
    for code in available():
        rule = load(code).get("detect", {})
        if rule.get("script"):
            found.append((rule.get("priority", 0), code, re.compile(rule["script"]),
                          rule.get("min_share", 0)))
    return [(code, script, share) for _, code, script, share in sorted(found, key=lambda f: (-f[0], f[1]))]


def _latin_fallback():
    """The pack that Latin text without word evidence falls back to, or None."""
    return next((c for c in available() if load(c).get("detect", {}).get("latin_fallback")), None)


def detect(text):
    """Best-effort detection from the packs' data; returns a language code or DEFAULT.

    1. Script rules (``detect.script``), by ``priority``: the first pack whose script occurs at
       least ``min_share`` times the number of Latin letters wins.
    2. Text dominated by a non-Latin script that no pack claims is DEFAULT.
    3. Latin text: the pack whose ``detect_words`` occur most often; ties and zero scores go
       to the ``latin_fallback`` pack.
    """
    latin = len(_LATIN.findall(text))
    for code, script, share in _detectors():
        hits = len(script.findall(text))
        if hits and hits >= share * latin:
            return code
    letters = len(_LETTER.findall(text))
    if not latin or letters - latin >= latin:
        return DEFAULT
    fallback = _latin_fallback()
    words = Counter(_WORD.findall(text.lower()))
    scores = {code: sum(words[w] for w in load(code)["detect_words"]) for code in available()}
    best = max(scores, key=lambda c: (scores[c], c == fallback)) if scores else None
    return best if best and scores[best] else fallback or DEFAULT
