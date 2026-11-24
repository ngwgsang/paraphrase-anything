# AGENTS.md

Guidelines for AI coding agents (and humans) contributing to **paraphrase-everything**.

## Project

A paraphrase skill for AI agents. The LLM rewrites; deterministic Python tooling protects
spans that must not change, verifies fidelity against the original, and measures divergence.

## Layout

```
skills/paraphrase-anything/
├── SKILL.md                      # skill entry point and workflow
├── references/                   # modes.md, preservation.md, languages/<code>.md
└── scripts/
    ├── pe.py                     # CLI entry: python scripts/pe.py <command>
    └── paraphrase_everything/    # core package
        ├── cli.py                # argparse CLI, JSON output
        ├── protect.py            # mask/restore opaque spans
        ├── check.py              # fidelity check (errors / warnings / accepts)
        ├── metrics.py            # divergence, length, pairwise variant metrics
        ├── harness.py            # pe run: session state machine, passes 1–5, gates
        ├── planning.py           # analysis/plan validators, plan adherence
        ├── entailment.py         # entailment pairs and verdict checks (last text gate)
        ├── modes.json            # advisory bands per mode
        ├── presets.json          # harness presets: passes, gates, judge (references/presets.md)
        ├── text.py               # sentence splitting, marker matching
        └── lang/                 # <code>.json language data, loader, pack contract (pack.py)
tests/                            # unittest suite
.dev/docs/                        # local-only stories and roadmap (git-ignored)
```

## Commands

```bash
python -m unittest discover -s tests                   # run all tests
python skills/paraphrase-anything/scripts/pe.py --help  # CLI help
```

## Design principles

1. **The original is canonical.** Every check compares against the original input.
2. **The LLM writes, code verifies.** Certain errors must be fixed; suspicious changes may
   be accepted with a reason.
3. **Metrics advise, they do not dictate** (except explicit length targets).
4. **Zero install.** Core code uses the Python ≥ 3.9 standard library only. Optional
   dependencies go into future extras, never into core.
5. **Load only what is needed; extend by adding files, not editing core.**

## Code rules

- **No language-specific literals in Python code.** Negation/hedge markers, terminators,
  clichés, and number formats live in `lang/<code>.json`. A test enforces this.
- Data and config files are **JSON** (no `tomllib`, which needs 3.11).
- CLI output is JSON on stdout; exit codes: `0` ok, `1` completed with issues, `2` usage or input error.
- Every input-reading command accepts a path, `-` (stdin), or `--text`.
- Read and write files as UTF-8 with `newline=""` to preserve line endings.
- **Every function, method, and class has a short docstring** describing what it does
  (one line is usually enough; add details only for non-obvious behaviour). This includes
  private helpers and nested functions; test methods are exempt because their names describe
  them. A test enforces this.
- Match the surrounding style: comments only where the reason is not obvious.
- Every change ships with tests, including vi / en / ja cases where language matters.
- When changing CLI flags or `modes.json`, update `SKILL.md` and `references/`; `tests/test_skill.py` fails on drift.
- Adding a language is data only: `pe lang new <code>`, then fill `lang/<code>.json` (including
  fixtures) and `references/languages/<code>.md` until `pe langs` shows tier 1. Core code must not
  name a language code; a test enforces this. See `lang/README.md`.

## Documentation

- All docs, stories, comments, and commit messages are written in **English**.
- Stories live in `.dev/docs/stories/NNN-slug.md`, indexed in `.dev/docs/README.md`.
  This folder is local-only and never committed.
- When implementing a story: update its **Status**, tick acceptance criteria, and record any
  deviation from the plan in the **Decision log** of `.dev/docs/README.md`.

## Workflow

1. Pick the next story from the roadmap in `.dev/docs/README.md`.
2. Implement it with tests; run the full test suite until it passes.
3. Update the story status and decision log.
4. If that story completes a milestone, bump the version (see **Versioning**).
5. **Stop and ask the maintainer whether to commit and push** before starting the next story.
   Never commit, push, or begin another story without that confirmation.

## Versioning

Semantic versioning; while below 1.0 each roadmap milestone is a minor release:

| Milestone | Version |
|-----------|---------|
| MVP | 0.1.0 |
| v0.2 | 0.2.0 |
| v0.3 | 0.3.0 |
| v0.4 | 0.4.0 |

- **Minor bump** when the last story of a milestone is done (every story listed for it in
  `.dev/docs/README.md` is done or explicitly deferred). Never bump for a partly done milestone.
- **Patch bump** (`0.3.0` → `0.3.1`) only for fixes released between milestones, when the
  maintainer asks for one.
- How: set `version` in `.claude-plugin/plugin.json` (the single source) and `__version__` in
  `paraphrase_everything/__init__.py`, run `python scripts/sync_manifests.py --write`, then
  `python scripts/sync_manifests.py --check` and the full test suite (`tests/test_plugin.py`
  fails on drift).
- Commit the bump on its own: `Release 0.3.0 (milestone v0.3)`, and record it in the decision log.
- Git tags (`v0.3.0`) and GitHub releases are outward-facing: create them only when the
  maintainer asks.

## Commits and pull requests

- One story (or one coherent change) per commit; imperative subject line, e.g.
  `Add fidelity check (story 002)`.
- Never commit `.dev/`, virtual environments, or caches.
- Do not skip hooks or force-push to `main`.
