---
name: aggregates-only
description: The privacy guardrail for this repo. Use this before writing ANY file under results/, examples/*/results/, slides, README examples, or PR descriptions, and whenever adding a new output format, a new column, a new slide, or a debugging print. Also use it when reviewing a PR. Cohort members are real early-career faculty who never asked to be benchmarked; nothing identifying them may leave the local data/ and .cache/ directories.
---

# Aggregates only

## The rule

Any artifact that can be committed, shared, or shown (everything under `results/`, every slide, every figure, every PR description, every log line that CI captures) contains aggregates about the cohort and nothing that identifies a cohort member.

Identifying means: display name, name variants, OpenAlex author ID (`A` followed by digits), ORCID, per-person metric rows, per-person paper lists, or a small enough cross-tab that a person can be inferred (any cell with fewer than 5 people is suppressed and shown as `<5`).

The subject is the exception. They ran the tool on themselves, and their name, ID, and paper list may appear in their own report.

## What is allowed in results

- Quartiles, means, counts, CIs, funnel counts.
- Venue lists with paper counts (venues are not people).
- Institution lists with cohort-member counts, only when the count is 5 or more; otherwise bucket into "other".
- Topic lists.
- The subject's own metrics and paper list.

## What is never allowed in results

- Any cohort member's name, even in a "sanity check" or "who's who" list.
- Any per-member CSV, even with names stripped (metric rows plus institution plus start year re-identify people trivially).
- The candidate pool or any cache file.
- Screenshots or pastes of the above in PR descriptions or issues.

## Where names may live

- `data/` and `.cache/`: local only, gitignored, never committed.
- Terminal output of `tenuretrack show-cohort`: prints names and institutions to stdout so the user can eyeball whether the cohort makes sense. Never writes a file. Prints a one-line reminder that this output is for the user's eyes only.

## Enforcement

`tenuretrack/guardrail.py` provides `assert_aggregates_only(path, cohort_names, cohort_ids)`. Every writer of a results file calls it before returning. It:

1. Rejects any line matching `\bA\d{7,}\b` or an ORCID pattern.
2. Rejects any occurrence of a cohort member's display name or alternative name (case-insensitive, accent-stripped).
3. Rejects the prescriptive vocabulary: `expected`, `required`, `threshold`, `bar`, `target`, `on track`, `at risk`, `behind`, `ahead`, `quota`, `minimum` (except in the phrase "minimum cell size").
4. Rejects any CSV whose row count equals the cohort size (a per-person table in disguise).

`tests/test_guardrail.py` runs it over every file in `examples/*/results/` on every CI run. A guardrail failure blocks the PR.

## Wording

Reports describe distributions. Use "median", "p25", "p75", "typical", "range", "above p75", "below p25". Do not translate positions into judgments.
