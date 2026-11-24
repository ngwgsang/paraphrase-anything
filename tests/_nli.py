"""Test helper: judge every entailment pair of a session as ``entail`` in both directions."""

import json
from pathlib import Path

import _path  # noqa: F401
from paraphrase_everything import harness


def judge_all(session_dir, judge="self"):
    """Write an all-``entail`` verdict file for the current rewrite and return the pairs."""
    found = harness.entailment_pairs(session_dir)
    data = {"judge": judge, "pairs": [
        {"pair": p["pair"], "forward": "entail", "backward": "entail",
         "evidence": {"src": p["original"], "rew": p["rewritten"]},
         "reason": "the flagged change keeps the meaning" if p["flags"] else ""}
        for p in found["pairs"]]}
    Path(found["file"]).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return found["pairs"]
