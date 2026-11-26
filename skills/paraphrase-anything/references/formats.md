# Input formats

`pe extract`, `pe rebuild`, and `pe run init` read these formats. Only the prose segments are
rewritten; everything else in the file is copied back byte for byte, with its line endings.

| Format | Extensions | Rewritten | Never changed |
|--------|------------|-----------|---------------|
| `text` | `.txt` | paragraphs (blank-line separated) | indentation, line breaks, line endings |
| `markdown` | `.md`, `.markdown` | headings, list items, block quotes, paragraphs | front matter, code, tables, HTML blocks, link definitions |
| `srt` | `.srt` | cue text | indices, timing lines |
| `vtt` | `.vtt` | cue text | header, timing lines, `NOTE` / `STYLE` / `REGION` blocks |

A test keeps this table in sync with the formats the code registers.

## Choosing the format

`--format` picks it explicitly. Otherwise the file extension decides; without a known extension
the content is sniffed (WebVTT header, then SRT timing lines, then Markdown syntax), and plain
`text` is the fallback. `pe run init` decides by extension only.

## Format options

Some formats take options, passed as `--format-option key=value` (repeatable) to `pe extract`,
`pe rebuild`, and `pe run init`. A format rejects options it does not declare. Option types:
`str`, `list` (comma-separated), `bool` (`true` / `false`), and `int`. None of the formats above
declare options yet.

## Adding a format

Add one module to `scripts/paraphrase_everything/io/` with `extract(source, **options)`,
`rebuild(source, rewritten, **options)`, and a `SPECS` list (name, extensions, output extension,
optional `sniff` and `priority`, optional `options`); see the docstring of `io/__init__.py`. Then
add a sample file `tests/format_samples/<name><output extension>` so the shared contract test
runs on it, and a row to the table above. No core file needs editing.
