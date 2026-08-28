---
name: cohort-methodology
description: The rules for building a tenure-clock subfield cohort and computing publication metrics on it. Use this whenever implementing or changing candidate pooling, core-topic share, career-start estimation, the PI-like filter, through-year-N metrics, venue quartiles, bootstrap quartiles, subject comparison horizons, or the chaperone (led vs co-authored) analysis. Also use it when a user asks why a cohort looks wrong or how a number was computed.
---

# Cohort methodology

The full written method lives in `docs/methods.md` and must stay in sync with the code. This skill is the implementation-level summary.

## Definitions

- **Career year**: `publication_year - start_year + 1`. Year 1 is the calendar year the appointment began.
- **Window**: the subject's or cohort member's career years 1 through N. Default N = 6 (the typical tenure review point).
- **Led paper**: the person is last author, or `is_corresponding` is true for them. First author on a paper where they are not last/corresponding counts as "first-not-led" (written in someone else's group). Everything else is "middle".
- **Journal article**: OpenAlex `type == "article"`, source type journal, not a preprint server. Book chapters, conference papers, editorials, errata are excluded on both sides of every comparison (configurable, but symmetric).
- **Venue impact**: the source's `summary_stats.2yr_mean_citedness`. Missing values are left missing, never imputed.
- **Top-quartile venue**: venue impact at or above the 75th percentile of venue impacts across all window papers of the headline cohort. Computed within the cohort, never from a global list.

## The funnel

Emit a count after every step to `results/funnel.csv`.

1. **Candidate pool**: authors with `topics.id` in the configured topic set, `works_count >= 10`, affiliation country in `countries` (default `["US"]`).
2. **Core-topic share**: sum of `topics[].share` (or count-weighted) over the configured topics is at least `core_topic_share_min` (default 0.4). This is the main lever for cohort tightness: on a measured six-topic pool of 82,601 authors it left 27,409 people at 0.25, 4,738 at 0.4, and 836 at 0.5.
3. **University**: at least one affiliation with `institution.type == "education"`. Drop industry, government lab, and hospital-only profiles. National-lab-plus-university people stay.
4. **Fresh tenure-track-shaped start** in the cohort window (default 2008 to 2018). See career start below. Drop anyone whose start cannot be estimated with confidence.
5. **PI-like headline cohort**: at least `min_led_papers` (default 3) led journal articles in the window and at least one paper in each of two distinct window years. This removes long-term postdocs, staff scientists, and profile fragments.
6. **Identity confidence**: drop profiles that look merged (topic profile bimodal across fields, affiliations in two countries simultaneously, works_count implausible for the years active).

Report the headline cohort size `n` and the number of contributing institutions. If `n < 40`, print a loud warning and add a caveat that quartiles are indicative only.

## Career start estimation

Goal: the year the person began their first independent faculty appointment. Signals, in priority order:

1. ORCID employment records when present in the OpenAlex author record (rare but authoritative).
2. First year at an institution where they subsequently have at least two led papers, and where the institution differs from their PhD/postdoc institution inferred from earlier first-author-only years.
3. First led paper year minus 1, if the affiliation history is too thin for rule 2.

Confidence is "high" if rules 1 or 2 fire cleanly, "low" otherwise. Only high-confidence starts enter the headline cohort. Persist the estimate and its rule in the private `data/` directory, never in `results/`.

For the subject, `start_year` comes from `benchmark.yaml` and is trusted.

## Metrics per person through year N

For N in 1..6 and for the subject's current career year:

- `pubs`: journal articles in career years 1..N with the person's institutional byline (subject) or any byline (cohort; the cohort is already anchored by the start estimate).
- `led`: led papers among those. `lead_share = led / pubs`.
- `citations`: sum of `cited_by_count` for window papers (as of today, so cohort papers have had far longer to accrue; see comparison rules).
- `h_index`: computed from window papers only.
- `venue_impact_median`: median venue impact over window papers with a resolvable source.
- `top_quartile_share`: fraction of window papers in top-quartile venues.

## Quartiles and uncertainty

For each metric and horizon: p25, p50, p75 across cohort members. Cluster bootstrap resampling people (not papers), 2,000 iterations, for 95% CIs on each quartile. Cohort members are the unit of analysis everywhere.

## Subject comparison rules

- Compare only at the same career year. If the subject is in year 4, compute the cohort through year 4 and compare there. Also report the through-year-6 norms as the destination.
- Report the subject's citations but do not place them against cohort quartiles. Cohort window papers are 8 to 18 years old; the subject's are 0 to N. Say this explicitly in the report.
- Position words: "below p25", "between p25 and median", "at the median", "between median and p75", "above p75". Never "behind", "ahead", "on track", "at risk".

## Chaperone analysis

For every headline-cohort window paper, classify the member's role (led, first-not-led, middle). Compute:

- Top-quartile venue rate per role, pooled across papers.
- Led-vs-middle gap with a cluster-bootstrap 95% CI (resample people).
- Paired within-person comparison for people with at least 3 venue-resolvable papers in both led and middle classes: median within-person top-quartile share per class and a sign test on who does better on co-authored papers.
- Per-venue co-authored share for the top 15 venues by paper count.

Cite Sekara et al., "The chaperone effect in scientific publishing", PNAS 2018, doi 10.1073/pnas.1800471115, and state that this is a cross-sectional approximation of their longitudinal design.
