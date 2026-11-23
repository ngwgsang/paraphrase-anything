"""Split long input into coherent chunks and merge them back (story 003).

Splitting is lossless: the chunks concatenate to exactly the input. Cuts fall on headings,
then paragraph breaks, then sentence ends, never inside a sentence, list item, table row,
fenced code block, or placeholder.
"""

import json
import re
from pathlib import Path

from . import lang
from .text import split_sentences

DEFAULT_MAX_WORDS = 1200
DEFAULT_THRESHOLD = 3000  # words; below this the whole text is one chunk
MANIFEST = "manifest.json"

_CJK = re.compile(r"[぀-ヿ一-鿿]")
_WORD = re.compile(r"\w+")
_HEADING = re.compile(r"#{1,6}\s")
_FENCE = re.compile(r"[ \t]*(`{3,}|~{3,})")


class ChunkError(ValueError):
    """Raised when chunks cannot be written or merged."""


def size(text):
    """Size in words: Latin-script words plus half the CJK characters."""
    cjk = len(_CJK.findall(text))
    return len(_WORD.findall(_CJK.sub(" ", text))) + cjk // 2


def _blocks(text):
    """Split into ``(text, is_heading)`` blocks; trailing blank lines stay with their block."""
    blocks, current, heading = [], [], False
    in_fence, fence_mark, prev_blank = False, "", False

    def flush():
        """Close the block being built."""
        nonlocal current, heading
        if current:
            blocks.append(("".join(current), heading))
        current, heading = [], False

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        fence = _FENCE.match(line)
        if in_fence:
            current.append(line)
            if fence and fence.group(1)[0] == fence_mark[0] and len(fence.group(1)) >= len(fence_mark) \
                    and stripped == fence.group(1):
                in_fence = False
            prev_blank = False
            continue
        starts_heading = bool(_HEADING.match(line))
        if current and (prev_blank or starts_heading or heading):
            flush()
        if fence:
            in_fence, fence_mark = True, fence.group(1)
        if not current:
            heading = starts_heading
        current.append(line)
        prev_blank = not stripped
    flush()
    return blocks


def _pieces(block, data):
    """Split one oversize block into sentence pieces; whitespace stays with the previous piece."""
    starts = [s for s, _ in split_sentences(block, data)]
    if len(starts) < 2:
        return [block]
    starts[0] = 0
    return [block[a:b] for a, b in zip(starts, starts[1:] + [len(block)])]


def split(text, max_words=DEFAULT_MAX_WORDS, threshold=DEFAULT_THRESHOLD, lang_code="auto"):
    """Return ``(chunks, info)``; ``"".join(chunks) == text`` always holds."""
    total = size(text)
    info = {"words": total, "threshold": threshold, "needs_chunking": total > threshold}
    if not text or total <= threshold:
        return [text] if text else [], info
    data = lang.load(lang.detect(text) if lang_code == "auto" else lang_code)

    units = []  # (text, is_heading); oversize blocks fall back to sentences
    for block, heading in _blocks(text):
        if size(block) > max_words and not _FENCE.match(block):
            units += [(piece, heading and i == 0) for i, piece in enumerate(_pieces(block, data))]
        else:
            units.append((block, heading))

    chunks, current, words = [], [], 0

    def close(upto=None):
        """Emit the first ``upto`` units of the current chunk and keep the rest."""
        nonlocal current, words
        upto = len(current) if upto is None else upto
        if upto:
            chunks.append("".join(t for t, _ in current[:upto]))
        current = current[upto:]
        words = sum(size(t) for t, _ in current)

    for unit in units:
        n = size(unit[0])
        if current and words + n > max_words:
            headings = [i for i, (_, h) in enumerate(current) if h and i > 0]
            cut = headings[-1] if headings else len(current)
            if current[cut - 1][1]:  # never end a chunk on a bare heading
                cut -= 1
            if cut > 0:  # a lone heading stays with the unit that follows it
                close(cut)
        current.append(unit)
        words += n
    close()
    info["needs_chunking"] = len(chunks) > 1
    return chunks, info


def write_chunks(chunks, info, out_dir):
    """Write ``NNN.md`` files and ``manifest.json`` into ``out_dir``; return the manifest."""
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    entries = []
    for i, chunk in enumerate(chunks, 1):
        name = f"{i:03d}.md"
        with open(path / name, "w", encoding="utf-8", newline="") as f:
            f.write(chunk)
        entries.append({"file": name, "words": size(chunk)})
    manifest = dict(info, chunks=entries)
    with open(path / MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def _read(path):
    """Read a UTF-8 file keeping its line endings."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def merge(chunk_dir, rewritten_dir=None):
    """Reassemble chunks in manifest order, optionally from rewritten copies in another folder.

    A rewritten chunk keeps the trailing blank lines of the original chunk, so paragraph
    breaks between chunks survive even if the rewrite dropped them.
    """
    base = Path(chunk_dir)
    try:
        manifest = json.loads(_read(base / MANIFEST))
    except FileNotFoundError:
        raise ChunkError(f"no {MANIFEST} in {base}") from None
    source = Path(rewritten_dir) if rewritten_dir else base
    parts = []
    for entry in manifest["chunks"]:
        original = _read(base / entry["file"])
        try:
            text = _read(source / entry["file"])
        except FileNotFoundError:
            raise ChunkError(f"missing chunk file: {source / entry['file']}") from None
        if source != base:
            tail = original[len(original.rstrip()):]
            text = text.rstrip() + tail
        parts.append(text)
    return "".join(parts)
