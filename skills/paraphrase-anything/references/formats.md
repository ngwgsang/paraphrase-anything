# Input formats

`pe extract`, `pe rebuild`, and `pe run init` read these formats. Only the prose segments are
rewritten; everything else in the file is copied back byte for byte, with its line endings.

| Format | Extensions | Rewritten | Never changed |
|--------|------------|-----------|---------------|
| `text` | `.txt` | paragraphs (blank-line separated) | indentation, line breaks, line endings |
| `markdown` | `.md`, `.markdown` | headings, list items, block quotes, paragraphs | front matter, code, tables, HTML blocks, link definitions |
| `srt` | `.srt` | cue text | indices, timing lines |
| `vtt` | `.vtt` | cue text | header, timing lines, `NOTE` / `STYLE` / `REGION` blocks |
| `json` | `.json` | string values (locale files) | keys, numbers, booleans, structure, indentation |
| `po` | `.po`, `.pot` | `msgstr` (or `msgid` in a template) | `msgid`, `msgctxt`, comments, flags, the header |

A test keeps this table in sync with the formats the code registers.

## Choosing the format

`--format` picks it explicitly. Otherwise the file extension decides; without a known extension
the content is sniffed (WebVTT header, then SRT timing lines, then Markdown syntax), and plain
`text` is the fallback. `pe run init` decides by extension only.

## Format options

Some formats take options, passed as `--format-option key=value` (repeatable) to `pe extract`,
`pe rebuild`, and `pe run init`. A format rejects options it does not declare. Option types:
`str`, `list` (comma-separated), `bool` (`true` / `false`), and `int`.

| Format | Option | Type | Effect |
|--------|--------|------|--------|
| `json` | `keys` | list | rewrite only values whose dotted key path matches a glob, e.g. `keys=checkout.*,errors.*` |

## Locale files (`json`, `po`)

- Each segment carries `context`: the dotted key path (`json`) or the source `msgid` (`po`), so
  the rewrite fits where the string is shown. Never edit keys or ids.
- Values that are empty, only placeholders, or a single short word (button labels like "Save")
  are not segments; `pe extract` lists them under `skipped` with the reason.
- Interpolation placeholders are protected spans: `{name}`, `{{name}}`, `%{name}`, `{0}`, printf
  `%s` `%d` `%1$s` `%(name)s` `%@`, and whole ICU `plural` / `select` blocks. A missing or
  changed placeholder is a `pe check` error, so the app still loads the string.
- `po`: in a catalog with translations, `msgstr` (and each `msgstr[n]`) is rewritten; in a
  template where every `msgstr` is empty, `msgid` and `msgid_plural` are. A field written over
  several `"..."` lines is written back one line per `\n`.
- Rewriting never translates: keep the language of each string.

## Adding a format

Add one module to `scripts/paraphrase_everything/io/` with `extract(source, **options)`,
`rebuild(source, rewritten, **options)`, and a `SPECS` list (name, extensions, output extension,
optional `sniff` and `priority`, optional `options`); see the docstring of `io/__init__.py`. Then
add a sample file `tests/format_samples/<name><output extension>` so the shared contract test
runs on it, and a row to the table above. No core file needs editing.
