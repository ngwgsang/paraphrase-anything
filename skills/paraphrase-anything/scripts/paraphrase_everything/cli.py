"""Command-line interface. Output is JSON on stdout unless ``--pretty`` is given.

Exit codes: 0 ok, 1 completed with issues, 2 usage or input error.
"""

import argparse
import json
import sys

from . import __version__, check, lang, metrics, protect

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
    """List installed language data."""
    langs = [{"code": c, "name": lang.load(c)["name"]} for c in lang.available()]
    return {"ok": True, "langs": langs}, EXIT_OK


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

    p = sub.add_parser("langs", help="list installed language data")
    p.set_defaults(func=cmd_langs)
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
