"""Command-line interface. Output is JSON on stdout unless ``--pretty`` is given.

Exit codes: 0 ok, 1 completed with issues, 2 usage or input error.
"""

import argparse
import json
import sys
from pathlib import Path

from . import __version__, check, chunk, facts, glossary, harness, lang, metrics, protect
from . import io as formats
from .lang import pack

EXIT_OK, EXIT_ISSUES, EXIT_ERROR = 0, 1, 2


def _read_input(args):
    """Read the single input from --text, stdin ('-'), or a file path."""
    if getattr(args, "text", None) is not None:
        return args.text
    source = args.input
    if source is None:
        raise SystemExit("error: provide an input path, '-' for stdin, or --text")
    if source == "-":
        return sys.stdin.read()
    # newline="" keeps CRLF/LF exactly as in the file.
    with open(source, encoding="utf-8", newline="") as f:
        return f.read()


def _write_text(path, text):
    """Write UTF-8 text to ``path`` without changing line endings."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _emit(result, pretty):
    """Print ``result`` as JSON, indented when ``pretty`` is set."""
    if pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False))


def _add_input(p):
    """Add the standard input path / --text arguments to a subparser."""
    p.add_argument("input", nargs="?", help="input file, or '-' for stdin")
    p.add_argument("--text", help="input text given inline")


def cmd_protect(args):
    """Mask opaque spans; return the masked text and placeholder map."""
    text = _read_input(args)
    try:
        masked, mapping = protect.protect(text, keep=args.keep or ())
    except protect.ProtectError as e:
        return {"ok": False, "error": str(e)}, EXIT_ERROR

    result = {"ok": True, "count": len(mapping["placeholders"])}
    if args.output:
        _write_text(args.output, masked)
        result["output"] = args.output
    else:
        result["text"] = masked
    if args.map:
        with open(args.map, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        result["map"] = args.map
    else:
        result["map"] = mapping
    return result, EXIT_OK


def cmd_restore(args):
    """Restore placeholders using a map; report missing or extra ones."""
    text = _read_input(args)
    with open(args.map, encoding="utf-8") as f:
        mapping = json.load(f)
    restored, report = protect.restore(text, mapping)
    if args.output:
        _write_text(args.output, restored)
        report["output"] = args.output
    else:
        report["text"] = restored
    return report, EXIT_OK if report["ok"] else EXIT_ISSUES


def _read_source(source, inline):
    """Read text from an inline value, stdin ('-'), or a file path."""
    if inline is not None:
        return inline
    if source is None:
        raise SystemExit("error: provide a path, '-' for stdin, or the matching --*-text option")
    if source == "-":
        return sys.stdin.read()
    with open(source, encoding="utf-8", newline="") as f:
        return f.read()


def cmd_check(args):
    """Run the fidelity check between an original and its rewrite."""
    if args.original == "-" and args.rewritten == "-":
        raise SystemExit("error: only one of original/rewritten can be read from stdin")
    original = _read_source(args.original, args.original_text)
    rewritten = _read_source(args.rewritten, args.rewritten_text)
    accept = []
    if args.accept:
        with open(args.accept, encoding="utf-8") as f:
            accept = json.load(f)
    report = check.check(original, rewritten, lang_code=args.lang,
                         keep=args.keep or (), accept=accept)
    return report, EXIT_OK if report["ok"] else EXIT_ISSUES


def _read_json_file(path):
    """Load a JSON file given by path, or from stdin when the path is '-'."""
    if path == "-":
        return json.loads(sys.stdin.read())
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_facts(args):
    """Validate a key-fact list against the original and, given a rewrite, verify it."""
    if [args.original, args.rewritten, args.facts].count("-") > 1:
        raise SystemExit("error: only one input can be read from stdin")
    original = _read_source(args.original, args.original_text)
    has_rewrite = args.rewritten is not None or args.rewritten_text is not None
    rewritten = _read_source(args.rewritten, args.rewritten_text) if has_rewrite else None
    if args.verdicts and rewritten is None:
        raise SystemExit("error: --verdicts needs a rewrite to judge")
    try:
        fact_list = facts.parse_facts(_read_json_file(args.facts))
        verdicts = facts.parse_verdicts(_read_json_file(args.verdicts)) if args.verdicts else None
    except (facts.FactsError, json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e)}, EXIT_ERROR
    report = facts.verify(original, fact_list, rewritten, verdicts, lang_code=args.lang,
                          max_facts=args.max_facts)
    return report, EXIT_OK if report["ok"] else EXIT_ISSUES


def cmd_chunk(args):
    """Split long input into chunk files plus a manifest."""
    text = _read_input(args)
    if args.max_words < 1:
        raise SystemExit("error: --max-words must be at least 1")
    chunks, info = chunk.split(text, max_words=args.max_words, threshold=args.threshold,
                               lang_code=args.lang)
    manifest = chunk.write_chunks(chunks, info, args.output)
    manifest["output"] = args.output
    return dict(manifest, ok=True), EXIT_OK


def cmd_merge(args):
    """Reassemble chunk files (or their rewritten copies) in manifest order."""
    try:
        text = chunk.merge(args.chunk_dir, args.rewritten_dir)
    except chunk.ChunkError as e:
        return {"ok": False, "error": str(e)}, EXIT_ERROR
    result = {"ok": True, "words": chunk.size(text)}
    if args.output:
        _write_text(args.output, text)
        result["output"] = args.output
    else:
        result["text"] = text
    return result, EXIT_OK


def cmd_glossary(args):
    """Extract a term glossary, or verify a rewrite against a settled glossary."""
    if args.glossary:
        if args.rewritten is None and args.rewritten_text is None:
            raise SystemExit("error: verifying needs a rewrite (--rewritten or --rewritten-text)")
        original = _read_input(args)
        rewritten = _read_source(args.rewritten, args.rewritten_text)
        try:
            entries = glossary.parse(_read_json_file(args.glossary))
        except (glossary.GlossaryError, json.JSONDecodeError) as e:
            return {"ok": False, "error": str(e)}, EXIT_ERROR
        report = glossary.verify(original, rewritten, entries)
        return report, EXIT_OK if report["ok"] else EXIT_ISSUES
    entries = glossary.extract(_read_input(args), keep=args.keep or (), terms=args.term or (),
                               min_count=args.min_count)
    result = {"ok": True, "count": len(entries)}
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        result["output"] = args.output
    else:
        result["glossary"] = entries
    return result, EXIT_OK


def _format_of(args, source):
    """Resolve the format from ``--format`` or by detecting it from the path and content."""
    if args.format != "auto":
        return args.format
    path = args.input if args.input not in (None, "-") and args.text is None else None
    return formats.detect(source, path)


def cmd_extract(args):
    """List the rewritable segments of a text, Markdown, SRT, or VTT input."""
    source = _read_input(args)
    fmt = _format_of(args, source)
    segments = formats.public(formats.extract(source, fmt))
    result = {"ok": True, "format": fmt, "count": len(segments), "segments": segments}
    if args.output:
        _write_text(args.output, json.dumps(result, ensure_ascii=False, indent=2))
        return {"ok": True, "format": fmt, "count": len(segments), "output": args.output}, EXIT_OK
    return result, EXIT_OK


def _rewritten_map(data):
    """Turn a rewritten-segments JSON value into ``{id: text}``."""
    items = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise formats.FormatError("segments JSON must be a list or an object with a 'segments' list")
    mapping = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int)                 or not isinstance(item.get("text"), str):
            raise formats.FormatError("each segment needs an integer 'id' and a string 'text'")
        mapping[item["id"]] = item["text"]
    return mapping


def cmd_rebuild(args):
    """Put rewritten segments back into the original document, keeping everything else."""
    source = _read_input(args)
    fmt = _format_of(args, source)
    try:
        rewritten = _rewritten_map(_read_json_file(args.segments))
        before = {s["id"]: s["text"] for s in formats.extract(source, fmt)}
        output = formats.rebuild(source, fmt, rewritten)
    except (formats.FormatError, json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e)}, EXIT_ERROR
    result = {"ok": True, "format": fmt, "changed": sum(1 for k, v in rewritten.items() if before[k] != v)}
    if fmt in ("srt", "vtt"):
        data = lang.load(args.lang if args.lang != "auto" else lang.detect(output))
        limits = dict(data["subtitle"])
        if args.max_line_chars is not None:
            limits["max_line_chars"] = args.max_line_chars
        if args.max_cps is not None:
            limits["max_cps"] = args.max_cps
        result["warnings"] = formats.srt.lint(output, limits)
    if args.output:
        _write_text(args.output, output)
        result["output"] = args.output
    else:
        result["text"] = output
    return result, EXIT_OK


def cmd_metrics(args):
    """Compute metrics for a pair, or pairwise divergence for variants."""
    if args.variants and not args.pairwise:
        raise SystemExit("error: --variant requires --pairwise")
    if args.pairwise:
        if args.variants and (args.inputs or args.variants_json):
            raise SystemExit("error: --variant cannot be combined with input files or --variants-json")
        if args.variants:
            texts = args.variants
        elif args.variants_json:
            texts = json.loads(_read_source(args.variants_json, None))
        else:
            if args.inputs.count("-") > 1:
                raise SystemExit("error: only one input can be read from stdin")
            texts = [_read_source(p, None) for p in args.inputs]
        if len(texts) < 2:
            raise SystemExit("error: --pairwise needs at least two variants")
        report = metrics.pairwise(texts, lang_code=args.lang, max_overlap=args.max_overlap)
        return report, EXIT_OK if report["ok"] else EXIT_ISSUES

    paths = args.inputs + [None] * (2 - len(args.inputs))
    if len(args.inputs) > 2:
        raise SystemExit("error: metrics compares two texts; use --pairwise for more")
    if paths.count("-") > 1:
        raise SystemExit("error: only one input can be read from stdin")
    original = _read_source(paths[0], args.original_text)
    rewritten = _read_source(paths[1], args.rewritten_text)
    try:
        report = metrics.compare(original, rewritten, lang_code=args.lang, mode=args.mode,
                                 target_ratio=args.target_ratio)
    except ValueError as e:
        return {"ok": False, "error": str(e)}, EXIT_ERROR
    return report, EXIT_OK if report["ok"] else EXIT_ISSUES


def cmd_detect(args):
    """Detect the language of the input."""
    code = lang.detect(_read_input(args))
    return {"ok": True, "lang": code, "supported": code in lang.available()}, EXIT_OK


def cmd_langs(args):
    """List installed language packs with their tier, supported checks, and open problems."""
    langs = pack.coverage_table()
    ok = not any(row["problems"] for row in langs)
    return {"ok": ok, "langs": langs}, EXIT_OK if ok else EXIT_ISSUES


RUN_FLAGS = {"init": {"mode", "persona", "lang", "passes", "gates", "preset", "variants", "max_rounds", "output"},
             "rewind": {"to"}}
RUN_DEFAULTS = {"mode": None, "persona": None, "lang": "auto", "passes": None, "gates": None, "preset": None,
                "variants": None, "max_rounds": None, "output": None, "to": None}


def cmd_run(args):
    """Drive a harness session: init, next, submit, pairs, status, rewind, report."""
    misplaced = [f"--{k.replace('_', '-')}" for k, default in RUN_DEFAULTS.items()
                 if getattr(args, k) != default and k not in RUN_FLAGS.get(args.action, set())]
    if misplaced:
        return {"ok": False, "error": f"pe run {args.action} does not take {', '.join(misplaced)}"}, EXIT_ERROR
    try:
        if args.action == "init":
            text = _read_input(argparse.Namespace(input=args.target, text=None))
            max_rounds = harness.DEFAULT_MAX_ROUNDS if args.max_rounds is None else args.max_rounds
            fmt = formats.EXTENSIONS.get(Path(args.target).suffix.lower(), "text") if args.target != "-" else "text"
            state = harness.init(text, args.output, mode=args.mode or "standard", persona=args.persona,
                                 lang_code=args.lang, passes=args.passes, max_rounds=max_rounds,
                                 gates=args.gates, preset=args.preset, fmt=fmt, variants=args.variants or 1)
            return {"ok": True, "session": state["session_dir"], "passes": state["passes"],
                    "gates": state["gates"], "resolutions": state["resolutions"],
                    "lang": state["lang"], "format": state["format"], "long": state["long"],
                    "variants": state["variants"], "current": state["current"]}, EXIT_OK
        if args.action == "next":
            task = harness.next_task(args.target)
            return dict(task, ok=task["step"] != "incomplete"), EXIT_ISSUES if task["step"] == "incomplete" else EXIT_OK
        if args.action == "submit":
            result = harness.submit(args.target)
            return result, EXIT_OK if result["ok"] else EXIT_ISSUES
        if args.action == "pairs":
            return harness.entailment_pairs(args.target), EXIT_OK
        if args.action == "status":
            return dict(harness.status(args.target), ok=True), EXIT_OK
        if args.action == "rewind":
            if not args.to:
                raise harness.HarnessError("pe run rewind needs --to <pass>")
            return harness.rewind(args.target, args.to), EXIT_OK
        report = harness.write_report(args.target)
        return dict(report, ok=report["status"] == "complete"), EXIT_OK if report["status"] == "complete" else EXIT_ISSUES
    except harness.HarnessError as e:
        return {"ok": False, "error": str(e)}, EXIT_ERROR


def cmd_lang(args):
    """Scaffold a new language pack (``pe lang new <code>``)."""
    try:
        created = pack.scaffold(args.code, args.name or args.code, skill_dir=args.skill_dir or pack.SKILL_DIR,
                                length_unit=args.unit)
    except (ValueError, FileExistsError) as e:
        return {"ok": False, "error": str(e)}, EXIT_ERROR
    return {"ok": True, "created": created, "tier": 0, "next": [
        "fill in markers, terminators, separators, and the detect block in the data file",
        "add fixtures (detect, sentences, negation, hedge) until `pe langs` shows no problems",
        "complete the TODO lines of the language note",
        f"for tier 2, add at least {pack.EVAL_CASES_FOR_TIER_2} eval cases in evals/cases/{args.code}/",
    ]}, EXIT_OK


def build_parser():
    """Build the argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(prog="pe", description="paraphrase-everything tooling")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("protect", help="mask code, URLs, LaTeX, HTML, and kept terms")
    _add_input(p)
    p.add_argument("-o", "--output", help="write masked text here instead of the JSON result")
    p.add_argument("--map", help="write the placeholder map here instead of the JSON result")
    p.add_argument("--keep", action="append", metavar="TERM", help="extra term to keep verbatim (repeatable)")
    p.set_defaults(func=cmd_protect)

    p = sub.add_parser("restore", help="put masked spans back and report placeholder issues")
    _add_input(p)
    p.add_argument("--map", required=True, help="placeholder map written by protect")
    p.add_argument("-o", "--output", help="write restored text here instead of the JSON result")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("check", help="verify a rewrite against the original")
    p.add_argument("original", nargs="?", help="original file, or '-' for stdin")
    p.add_argument("rewritten", nargs="?", help="rewritten file, or '-' for stdin")
    p.add_argument("--original-text", help="original given inline")
    p.add_argument("--rewritten-text", help="rewrite given inline")
    p.add_argument("--lang", default="auto", help="language code (default: detect from original)")
    p.add_argument("--keep", action="append", metavar="TERM", help="term that must survive verbatim (repeatable)")
    p.add_argument("--accept", help='JSON list of accepted warnings: [{"id": "w1", "reason": "..."}]')
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("facts", help="validate a key-fact list, or verify a rewrite against it")
    p.add_argument("original", nargs="?", help="original file, or '-' for stdin")
    p.add_argument("rewritten", nargs="?", help="rewritten file, or '-' for stdin (omit to only validate)")
    p.add_argument("--original-text", help="original given inline")
    p.add_argument("--rewritten-text", help="rewrite given inline")
    p.add_argument("--facts", required=True, metavar="PATH",
                   help='JSON list of facts: [{"id": "f1", "fact": "...", "anchors": ["42"]}] ("-" = stdin)')
    p.add_argument("--verdicts", metavar="PATH",
                   help='JSON list of verdicts: [{"id": "f1", "verdict": "kept|changed|lost", "note": "..."}]')
    p.add_argument("--lang", default="auto", help="language code (default: detect from original)")
    p.add_argument("--max-facts", type=int, default=facts.MAX_FACTS,
                   help="most facts allowed (default: %(default)s)")
    p.set_defaults(func=cmd_facts)

    p = sub.add_parser("chunk", help="split long input into chunks for section-by-section rewriting")
    _add_input(p)
    p.add_argument("-o", "--output", required=True, metavar="DIR", help="folder for NNN.md files and manifest.json")
    p.add_argument("--max-words", type=int, default=chunk.DEFAULT_MAX_WORDS,
                   help="target chunk size in words (default: %(default)s)")
    p.add_argument("--threshold", type=int, default=chunk.DEFAULT_THRESHOLD,
                   help="inputs up to this many words stay one chunk (default: %(default)s)")
    p.add_argument("--lang", default="auto", help="language code (default: detect)")
    p.set_defaults(func=cmd_chunk)

    p = sub.add_parser("merge", help="reassemble chunk files in order")
    p.add_argument("chunk_dir", help="folder written by chunk")
    p.add_argument("--rewritten-dir", metavar="DIR", help="folder with rewritten NNN.md files (default: chunk_dir)")
    p.add_argument("-o", "--output", help="write the merged text here instead of the JSON result")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("glossary", help="extract recurring terms, or verify a rewrite against a glossary")
    _add_input(p)
    p.add_argument("--keep", action="append", metavar="TERM", help="term to keep verbatim (repeatable)")
    p.add_argument("--term", action="append", metavar="TERM", help="term to render consistently (repeatable)")
    p.add_argument("--min-count", type=int, default=glossary.MIN_COUNT,
                   help="fewest occurrences to list a term (default: %(default)s)")
    p.add_argument("-o", "--output", help="write the glossary JSON here instead of the JSON result")
    p.add_argument("--glossary", metavar="PATH", help="verify mode: settled glossary JSON ('-' = stdin)")
    p.add_argument("--rewritten", help="verify mode: rewritten file")
    p.add_argument("--rewritten-text", help="verify mode: rewrite given inline")
    p.set_defaults(func=cmd_glossary)

    p = sub.add_parser("extract", help="list rewritable segments of a text, Markdown, SRT, or VTT file")
    _add_input(p)
    p.add_argument("--format", default="auto", choices=["auto", *sorted(formats.FORMATS)],
                   help="input format (default: detect from extension, then content)")
    p.add_argument("-o", "--output", help="write the segments JSON here instead of the JSON result")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("rebuild", help="put rewritten segments back into the original document")
    _add_input(p)
    p.add_argument("--segments", required=True, metavar="PATH",
                   help='rewritten segments JSON: [{"id": 1, "text": "..."}] ("-" = stdin)')
    p.add_argument("--format", default="auto", choices=["auto", *sorted(formats.FORMATS)],
                   help="input format (default: detect from extension, then content)")
    p.add_argument("-o", "--output", help="write the rebuilt document here instead of the JSON result")
    p.add_argument("--lang", default="auto", help="language code for subtitle limits (default: detect)")
    p.add_argument("--max-line-chars", type=int, help="subtitle line length warning limit (default: per language)")
    p.add_argument("--max-cps", type=float, help="subtitle reading speed warning limit in chars/second (default: per language)")
    p.set_defaults(func=cmd_rebuild)

    p = sub.add_parser("metrics", help="divergence and length metrics (advisory)")
    p.add_argument("inputs", nargs="*", help="original and rewrite, or variants with --pairwise ('-' = stdin)")
    p.add_argument("--original-text", help="original given inline")
    p.add_argument("--rewritten-text", help="rewrite given inline")
    p.add_argument("--lang", default="auto", help="language code (default: detect)")
    p.add_argument("--mode", choices=sorted(metrics.MODES), help="report advisory bands for this mode")
    p.add_argument("--target-ratio", type=float, help="enforced length target, e.g. 0.7 (±10%%)")
    p.add_argument("--pairwise", action="store_true", help="compare every pair of variants")
    p.add_argument("--variant", action="append", dest="variants", metavar="TEXT",
                   help="variant text given inline (repeatable)")
    p.add_argument("--variants-json", metavar="PATH", help="JSON list of variant strings ('-' = stdin)")
    p.add_argument("--max-overlap", type=float, default=metrics.MAX_PAIR_OVERLAP,
                   help="pairs above this overlap are too similar (default: %(default)s)")
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("detect", help="detect the input language")
    _add_input(p)
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("langs", help="list installed language packs: tier, checks, problems")
    p.set_defaults(func=cmd_langs)

    p = sub.add_parser("run", help="harness session: pe drives the workflow one task at a time")
    p.add_argument("action", choices=["init", "next", "submit", "pairs", "status", "rewind", "report"])
    p.add_argument("target", help="input path or '-' for init; the session directory otherwise")
    p.add_argument("-o", "--output", help="init: session directory (default: a new temp directory)")
    p.add_argument("--mode", choices=sorted(metrics.MODES), help="init: rewrite mode (default: standard)")
    p.add_argument("--persona", help="init: persona pack name from references/personas/")
    p.add_argument("--lang", default="auto", help="init: language code (default: auto-detect)")
    p.add_argument("--passes", help="init: comma-separated passes to enable (default: all available)")
    p.add_argument("--gates", help="init: comma-separated gates to run, e.g. 1,3,5 ('' for none; "
                   "the final floor check always runs)")
    p.add_argument("--preset", help="init: fast, standard, or strict (from presets.json)")
    p.add_argument("--variants", type=int, help="init: number of distinct rewrites (2-5; needs pass plan)")
    p.add_argument("--max-rounds", type=int, help=f"init: fix rounds per pass (default: {harness.DEFAULT_MAX_ROUNDS})")
    p.add_argument("--to", help="rewind: the pass to resume from")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("lang", help="manage language packs: 'pe lang new <code>' scaffolds one")
    p.add_argument("action", choices=["new"], help="what to do")
    p.add_argument("code", help="language code, e.g. ko or pt-br")
    p.add_argument("--name", help="display name of the language (default: the code)")
    p.add_argument("--unit", choices=["word", "char"], default="word",
                   help="length unit: word for space-separated scripts, char otherwise (default: %(default)s)")
    p.add_argument("--skill-dir", help="skill folder to write into (default: this skill)")
    p.set_defaults(func=cmd_lang)
    return parser


def main(argv=None):
    """CLI entry point: parse arguments, run the command, print JSON, return the exit code."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        result, code = args.func(args)
    except OSError as e:
        result, code = {"ok": False, "error": str(e)}, EXIT_ERROR
    _emit(result, args.pretty)
    return code
