# Build plan

One task per PR, in order. Each PR must include tests and pass `make test`. Open the PR with a summary of what was built, what needs the maintainer's input, and (for network tasks) how many OpenAlex requests the live run made.

## Task 1: Scaffold
- `pyproject.toml` (typer, httpx, pyyaml, pandas, numpy, python-pptx, pytest), `src/tenuretrack/`, `Makefile` (`test`, `lint`, `run`, `chaperone`, `slides`).
- `config.py`: load and validate `benchmark.yaml` (schema in `benchmark.example.yaml`).
- `openalex.py`: client with on-disk cache (`.cache/`, keyed by request hash), `mailto` from env, rate limiting, retry with backoff on 429/5xx, retry sleep capped at 60 s, clear `QuotaExhausted` error, cursor pagination. Follow `.claude/skills/openalex-api`.
- `guardrail.py`: `assert_aggregates_only(path)` that scans any results file for author IDs (`A\d{7,}`), ORCIDs, and any name from the cohort roster, plus the forbidden prescriptive words. Follow `.claude/skills/aggregates-only`.
- CLI stub with all subcommands registered.
- CI workflow runs tests on push.

## Task 2: Subject resolution and topic suggestion (`init`)
- Given `--orcid`, fetch the subject's OpenAlex author record and works.
- Anchor the subject's window to `institution_ror` bylines from `start_year` onward (career year = calendar year minus start year plus one).
- Propose 4 to 6 OpenAlex topics ranked by share of the subject's window papers, with the topic's top venues shown so the user can sanity-check.
- Write `benchmark.yaml` with the proposed topics; the user edits before `run`.
- Handle split profiles: if the subject's works at `institution_ror` are spread across several author IDs, union them by DOI and record the alt IDs in the yaml.

## Task 3: Candidate pool
- Pull authors with substantial work in the configured topics (see cohort-methodology skill for the query).
- Store the pool gzipped under `data/` (gitignored). Pools can exceed 100 MB uncompressed.
- Apply the first filters: core-topic share, country, institution type.
- Emit funnel counts at each step to `results/funnel.csv`.

## Task 4: Career start estimation
- For each candidate, estimate the year of first independent (tenure-track-shaped) start using affiliation history plus the first lead-author paper at that institution. Rules in `docs/methods.md`.
- Keep only starts inside the cohort window (default 2008 to 2018).
- Drop ambiguous or low-confidence cases; count them in the funnel.

## Task 5: Metrics and quartiles
- Per cohort member, compute through year N (N = 1..6, plus the subject's current career year): publications (journal articles only), lead-author publications (last or corresponding), lead share, citations, h-index, median venue impact, share in top-quartile venues. Venue impact is `summary_stats.2yr_mean_citedness` of the source; top-quartile is computed within the cohort's own venue distribution.
- Quartiles (p25/p50/p75) with cluster-bootstrap CIs resampling people.
- Write `results/benchmarks.csv` and `results/benchmarks.md` (aggregates only, guardrail enforced).

## Task 6: Subject comparison and report
- Same metrics for the subject through their current career year, cohort re-computed at that horizon.
- Citations reported for the subject but explicitly not compared.
- `results/report.md`: norms table, subject-vs-cohort table, venue list, funnel, caveats section.

## Task 7: Chaperone report
- Classify every cohort window paper by the member's role (led = last or corresponding; first-not-last; middle).
- Top-quartile venue rate by role, cluster-bootstrap CI on the led-vs-middle gap, paired within-person comparison with a sign test.
- `results/chaperone.md` and `.csv`. Rerunnable with no network from cache.

## Task 8: Slides
- `slides` subcommand builds a six-slide PPTX from `results/` following `.claude/skills/deck-builder`. Export a PDF preview if LibreOffice is available; skip cleanly if not.

## Task 9: Example 1, Taylor Sparks
- Run the full pipeline on `examples/taylor-sparks/benchmark.yaml`. Commit `results/` and the deck. This subject is past year 6, so the through-year-6 benchmark applies directly and the comparison horizon is year 6.

## Task 10: Example 2, Huiwen Ji (battery materials)
- Run the full pipeline on `examples/huiwen-ji/benchmark.yaml`. Subject is mid-clock, so the report computes the cohort at her current career year as well as year 6. Commit `results/` and the deck.

## Task 11: Docs and release
- Finish `docs/methods.md` from the implemented code, `docs/beyond-papers.md`, `CITATION.cff`, README quick start verified end to end on a fresh clone, tag `v0.1.0`.
