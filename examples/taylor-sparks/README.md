# Example 1: Taylor Sparks, University of Utah

The maintainer's own record, run end to end. This is the acceptance test for the
whole pipeline and the reference for what the output looks like.

Reproduce it with:

```bash
export OPENALEX_MAILTO=you@university.edu
export OPENALEX_API_KEY=...           # free, from openalex.org/settings/api
cd examples/taylor-sparks
tenuretrack run
tenuretrack slides
```

## What it shows

A subject past career year 6, so the through-year-6 benchmark applies directly
and the comparison happens at year 6 rather than at his current career year 14.
Comparing a fourteen-year record against a six-year cohort would credit eight
extra years to one side.

The cohort is 1,091 people at 622 institutions, each estimated to have begun a
first independent faculty appointment between 2008 and 2018.

## Why the topic set was left as `init` proposed it

`init` proposed six topics and the run kept all six, which is not what the tool
recommends. Two of them, `T10018` (battery materials, 4 of the subject's papers)
and `T10059` (bone tissue engineering, 3 papers), contribute 58,000 of the
82,601 people in the candidate pool between them.

It is left that way on purpose, because a worked example that shows only the
tidy path is not much of a worked example. `results/funnel.csv` and the venue
table in `report.md` are what a reader should use to judge whether a cohort is
answering their question, and this one shows a subfield drawn wider than the
subject's own work. Trimming those two topics takes the pool to 26,212 and would
give a tighter, more defensible cohort.

## Two known limitations visible in this output

`Bulletin of the American Physical Society` supplies 932 of the cohort's 122,111
window papers and sits at the top of the venue table with an impact of 0.00. It
is a meeting-abstract series that OpenAlex types as a journal, with an ISSN and
`is_core` set, so nothing in the data separates it from a real journal. It is
counted as articles on both sides of every comparison here. `cohort.excluded_venues`
exists to drop venues like it and is deliberately left empty in this example.

The start year is supplied by the subject and trusted. An earlier version of this
example ran with 2016 instead of 2013, which shifted the window from 2013-2018 to
2016-2021 and moved almost every position from a mix to "above p75". `init` now
checks the supplied year against the first institutional byline and says so when
they disagree.

## What is in `results/`

| File | What it holds |
|---|---|
| `report.pdf` | The whole report with the charts. This is the one to open first |
| `report.md` | The same report as text: the subject against the cohort, the clock year by year, the venue table, the funnel, the caveats |
| `benchmarks.md`, `benchmarks.csv` | Cohort quartiles per metric per career year, with bootstrap intervals |
| `chaperone.md`, `chaperone.csv` | Top-quartile venue rates by authorship role, pooled and within each person. Also a page in `report.pdf` |
| `funnel.csv` | How many people each filter removed |
| `subject.csv`, `venues.csv` | Machine-readable inputs to the deck and the PDF |
| `taylor-d-sparks.pptx` | The six-slide deck |
| `figures/` | The charts, shared by the deck and the report |

Everything here is aggregates only. The guardrail runs on this directory in CI.
The one person named is the subject, and only because he ran the tool on himself.
