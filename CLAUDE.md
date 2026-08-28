# CLAUDE.md

Project instructions for Claude Code working in this repository.

## What this repo is

`tenuretrack` is a public, open-source tool that builds a subfield cohort of early-career faculty from OpenAlex and computes publication norms (papers, lead-author papers, venue quality, citations, h-index) through each year of the tenure clock, then places one subject against that cohort at the same career year. Aggregates only. No names in outputs.

This is a clean-room build. Do not reference, fetch, or assume anything from any prior private repository. Everything here is built from the spec in this file, `TASKS.md`, `docs/methods.md`, and the skills in `.claude/skills/`.

## Read these first

- `TASKS.md`: the ordered build plan. One task per PR. Do not skip ahead.
- `docs/methods.md`: the cohort construction rules. The code must implement exactly these rules; if a rule needs to change, change the doc in the same PR.
- `.claude/skills/openalex-api`: how to call OpenAlex correctly (fields, filters, pagination, quota).
- `.claude/skills/cohort-methodology`: the funnel, career-start estimation, metrics definitions.
- `.claude/skills/aggregates-only`: the privacy guardrail. Non-negotiable.
- `.claude/skills/deck-builder`: the six-slide report format.

## Hard rules

1. **Aggregates only.** No file under `results/` may contain a cohort member's name, OpenAlex ID, ORCID, or per-person metric row. Enforce this in code (`tenuretrack/guardrail.py`) and in tests, not just in prose. The only person who may appear by name in results is the subject, and only because they ran the tool on themselves.
2. **Nothing with names gets committed.** `.cache/` and `data/` are gitignored. Tests use small synthetic fixtures, never real cached responses.
3. **Descriptive, not prescriptive.** Reports say "median", "p25", "p75", "range". They never say "expected", "required", "threshold", "bar", or "target". A test greps generated reports for those words.
4. **Every OpenAlex request carries `mailto`.** Read from `OPENALEX_MAILTO`. Refuse to run network stages if it is unset. Never hardcode an email address.
5. **Resumable.** Every network stage caches responses on disk keyed by request hash and skips work already done. A run that dies on quota must be restartable with zero repeated requests.
6. **Cite what the method borrows.** OpenAlex (Priem, Piwowar, Orr 2022) and the chaperone effect (Sekara et al., PNAS 2018, doi 10.1073/pnas.1800471115).

## Conventions

- Python 3.11+, `pyproject.toml`, `src/` layout, package name `tenuretrack`.
- CLI via `typer`: `tenuretrack init | run | chaperone | slides | show-cohort`.
- Config is a single `benchmark.yaml` per subject (see `benchmark.example.yaml`).
- `pytest` for everything; `make test` must pass before any PR is opened.
- No em-dashes in any prose, docs, docstrings, or slide text. Use commas, periods, or parentheses.
- Keep functions pure where possible (data in, data out) so tests can run without network.
- When a live run is needed, say so in the PR description with the request count and rough wall time.

## Examples

`examples/taylor-sparks/` holds a `benchmark.yaml` and is the acceptance test for the whole pipeline (see TASKS.md, task 9). Its `results/` directory is committed because it contains aggregates only; the guardrail test runs on it.

There is one worked example and it is the maintainer's own record. A second example using a colleague was planned and dropped: the report states a subject's tenure-clock extension in plain words, which is closer to personal circumstance than to publication data, and a public repository is not the place for a colleague's. Any future example needs the subject's explicit agreement to what the report will say about them, not just to being included. Prefer no second example over a borrowed one.

## When in doubt

Prefer dropping an ambiguous person from the cohort over guessing. Prefer a smaller, cleaner cohort over a bigger, noisier one. Prefer saying "we cannot compare this" (citations at different horizons) over a misleading comparison.
