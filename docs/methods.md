# Methods

This document is the authoritative description of how a cohort is built and how numbers are computed. The code implements exactly this; when the code changes, this file changes in the same pull request.

## 1. The question

At the same point on the tenure clock, what does the publication record of an early-career faculty member in a given subfield typically look like, and where does one specific person sit relative to that distribution?

"Typically" means quartiles across a cohort, never a single expectation. "Subfield" means a small set of OpenAlex topics chosen from the subject's own papers.

## 2. Data source

All data is from OpenAlex (CC0). Author records give affiliations by year and topic shares; work records give authorship positions, venue, year, and citations; source records give venue impact (`2yr_mean_citedness`). Nothing is scraped from university websites.

## 3. Subject

The subject supplies an ORCID, an institution ROR, and the first year of the tenure-line appointment. Career year is `publication_year - start_year + 1`. The subject's window papers are journal articles carrying the institution's byline in career years 1 through N. If the subject's works are split across several OpenAlex profiles, they are unioned by DOI.

Topics are proposed from the subject's window papers, ranked by share, and confirmed by the subject. Four to six topics is the working range. Topics that carry only one or two of the subject's papers, or that would pull a distinct community into the cohort, should be excluded and the exclusion noted.

## 4. Cohort funnel

| Step | Rule | Default |
|---|---|---|
| Candidates | Authors with any of the topics, at least 10 works, affiliation in the configured countries | US |
| Core-topic share | Sum of topic shares over the configured topics | at least 0.25 |
| University | At least one `education` affiliation | |
| Fresh start | Estimated first independent appointment inside the cohort window | 2008 to 2018 |
| PI-like | At least 3 led journal articles in the window, activity in at least 2 distinct window years | |
| Identity | Profile does not look merged or fragmented | |

Counts after every step are written to `results/funnel.csv`. Cohorts under 40 people carry a warning.

## 5. Career start estimation

For cohort members, the start year is estimated (the subject's is supplied):

1. ORCID employment record if present in OpenAlex.
2. First year at an institution where the person subsequently has at least two led papers and which differs from the institution of their earlier first-author-only years.
3. Fallback: year of first led paper minus one.

Only rules 1 and 2 produce high-confidence starts; only high-confidence people enter the headline cohort. The cohort window (2008 to 2018) guarantees every member has completed at least six career years by the time of analysis.

## 6. Metrics

Computed per person through year N, for N = 1..6 and for the subject's current career year:

- Publications (journal articles).
- Led publications: last author, or corresponding author when flagged. Lead share = led / publications.
- Citations: sum of current `cited_by_count` for window papers.
- h-index over window papers.
- Median venue impact over window papers with a resolvable source.
- Top-quartile venue share: fraction of window papers whose venue impact is at or above the 75th percentile of venue impacts across all headline-cohort window papers.

## 7. Quartiles and uncertainty

p25, p50, p75 per metric and horizon, with 95% confidence intervals from a cluster bootstrap that resamples people (2,000 iterations).

## 8. Comparison rules

- Compare only at matching career years.
- Citations are reported for the subject but never compared: cohort window papers are 8 to 18 years old, the subject's are 0 to N.
- Positions are stated as quartile locations, not judgments.

## 9. Chaperone analysis

Each headline-cohort window paper is classified by the member's role: led, first-not-led, or middle. Top-quartile venue rates are compared by role with a cluster-bootstrap CI on the led-vs-middle gap, plus a paired within-person comparison and sign test. This approximates, cross-sectionally, the longitudinal design of Sekara et al. (PNAS 2018).

## 10. Known limitations

- Name disambiguation in OpenAlex is imperfect; the conservative identity filter biases the cohort toward distinctive names.
- Corresponding-author flags are missing for many journal-years; last-author position is the robust signal.
- Venue impact is journal-level and field-dependent; the within-cohort quartile bar partly corrects for this, but a topic set that spans two citation cultures will show it.
- Career start is estimated from bylines for cohort members. Lecturer-to-tenure-line conversions, clinical appointments, and delayed starts are invisible.
- Conference papers, book chapters, software, datasets, patents, teaching, and outreach are outside the data. See `beyond-papers.md`.
