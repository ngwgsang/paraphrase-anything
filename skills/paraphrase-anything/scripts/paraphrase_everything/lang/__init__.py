"""Language data loader.

All language-specific literals live in ``<code>.json`` next to this file.
Code must never hard-code them (story 012, phase 1).
"""

import json
import re
from functools import lru_cache
from pathlib import Path

LANG_DIR = Path(__file__).parent
DEFAULT = "default"

_KANA = re.compile(r"[぀-ヿ]")
_CJK = re.compile(r"[぀-ヿ一-鿿]")
# Letters specific to Vietnamese, plus precomposed tone-marked vowels.
_VI = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯẠ-ỹ]")
_LATIN = re.compile(r"[A-Za-z]")


def available():
    """Codes of all installed languages, excluding the generic fallback."""
    return sorted(p.stem for p in LANG_DIR.glob("*.json") if p.stem != DEFAULT)


@lru_cache(maxsize=None)
def _read(code):
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


def detect(text):
    """Best-effort script-based detection; returns a language code or DEFAULT."""
    if _KANA.search(text):
        return "ja"
    cjk = len(_CJK.findall(text))
    latin = len(_LATIN.findall(text))
    if cjk and cjk >= latin:
        return DEFAULT  # Han-only text: could be zh or ja; no pack decides yet.
    if _VI.search(text):
        return "vi"
    if latin:
        return "en"
    return DEFAULT
