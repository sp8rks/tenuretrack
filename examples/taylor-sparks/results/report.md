# Taylor D. Sparks against materials chemistry, at career year 6

Taylor D. Sparks started a tenure-line appointment at University of Utah in 2013 and is now in year 14 of it.
That is longer than the cohort's window, so both sides are read at year 6: a 14-year record set against a 6-year one would credit the extra years to one side.

The cohort is 1091 people at 622 institutions, each estimated to have begun a first independent faculty appointment between 2008 and 2018 in materials chemistry. Taylor D. Sparks is not among them.

These numbers describe what a group of people did. They are not a standard, nobody in the cohort agreed to be measured, and no part of this says what any one career should look like.

This file is the whole story in text. `report.pdf` is the same story with the charts, `benchmarks.md` has every year of the clock in full, and the CSVs beside them hold the same numbers for anything that wants to read them.

## Taylor D. Sparks and the cohort at year 6

A quarter of the cohort sat below p25, half sat below the median, and a quarter sat above p75. The last column says which of those stretches this record falls in. It is a location in a distribution and nothing more.

| Through year 6 | This record | Cohort p25 | Cohort median | Cohort p75 | Where it falls |
|---|---|---|---|---|---|
| Journal articles | 35 | 14 | 23 | 38 | between the median and p75 |
| Led articles (last or corresponding) | 17 | 3 | 6 | 12 | above p75 |
| Share of articles led | 0.49 | 0.16 | 0.29 | 0.50 | between the median and p75 |
| Citations to those articles | 2593 | 410 | 942 | 2128 | not compared |
| h-index over those articles | 22 | 9 | 14 | 21 | above p75 |
| Median venue impact | 4.91 | 3.26 | 4.17 | 5.87 | between the median and p75 |
| Share in top-quartile venues | 0.17 | 0.09 | 0.21 | 0.36 | between p25 and the median |

### Why citations have no position

The cohort's papers in this window are eight to eighteen years old and Taylor D. Sparks's are at most 6. Citations accumulate with time, so setting one count against the other would measure the calendar rather than the work. The count is here because it is worth knowing, and unplaced because the comparison would not mean anything.

## The cohort year by year, up to year 6

The same cohort, measured at the end of each career year. This is the row to read if the record being compared is earlier on the clock, and it is also where a sudden jump or a flat stretch in a subfield shows up. Quartiles and confidence intervals for every year are in `benchmarks.md`.

| Cohort median | Year 1 | Year 2 | Year 3 | Year 4 | Year 5 | Year 6 |
|---|---|---|---|---|---|---|
| Journal articles | 3 | 6 | 10 | 15 | 19 | 23 |
| Led articles (last or corresponding) | 1 | 1 | 2 | 3 | 4 | 6 |
| Share of articles led | 0.17 | 0.25 | 0.25 | 0.27 | 0.28 | 0.29 |
| Citations to those articles | 106 | 241 | 399 | 584 | 789 | 942 |
| h-index over those articles | 2 | 5 | 7 | 10 | 12 | 14 |
| Median venue impact | 3.87 | 3.83 | 3.88 | 3.96 | 3.98 | 4.17 |
| Share in top-quartile venues | 0.00 | 0.17 | 0.18 | 0.20 | 0.20 | 0.21 |

## Where the subfield publishes

The journals the cohort used most, so that "top-quartile venue" can be checked against titles rather than taken on trust. Impact is `2yr_mean_citedness` from OpenAlex, a property of the journal and not of any paper in it, and the quartile is computed inside this cohort rather than against a global ranking.

| Venue | Cohort papers | Impact | Top quartile |
|---|---|---|---|
| Bulletin of the American Physical Society | 932 | 0.00 |  |
| Journal of Power Sources | 807 | 7.75 | yes |
| Journal of Materials Chemistry A | 657 | 8.23 | yes |
| ACS Applied Materials & Interfaces | 609 | 8.38 | yes |
| Physical review. B./Physical review. B | 593 | 3.79 |  |
| Journal of Alloys and Compounds | 539 | 6.09 |  |
| Chemistry of Materials | 515 | 6.39 |  |
| RSC Advances | 431 | 7.07 |  |
| Ceramics International | 403 | 5.87 |  |
| Electrochimica Acta | 387 | 4.93 |  |
| Journal of The Electrochemical Society | 373 | 3.73 |  |
| International Journal of Hydrogen Energy | 357 | 9.84 | yes |
| Materials Science and Engineering C | 334 | 0.00 |  |
| The Journal of Physical Chemistry C | 324 | 3.75 |  |
| Advanced Energy Materials | 313 | 18.63 | yes |

Read this list before trusting the counts above it. Some conference abstract series carry an ISSN and are typed as journals by OpenAlex, so they cannot be told apart from a journal in the data and are counted as articles here. A venue near the top of this table with an impact near zero is usually one of them, and every count in this report includes it.

## How the cohort was built

Every filter, in the order it ran, and how many people it left. This is the table to check when a cohort looks wrong: a step that removes almost everybody, or almost nobody, is usually the one to question.

| Step | Rule | People left | Removed |
|---|---|---|---|
| candidates | topics T11948\|T10440\|T10657\|T10018\|T10311\|T10059, at least 10 works, an affiliation in US, not the subject themselves | 82600 | 0 |
| core topic share | share of work in the subfield at least 0.4 | 4830 | 77770 |
| university | an affiliation of type education | 4737 | 93 |
| plausible years | byline years could contain a start between 2008 and 2018 | 4141 | 596 |
| career start estimated | a confident first independent start (at least 2 led papers at one institution, with earlier trainee years elsewhere) | 2015 | 2126 |
| start in window | estimated start between 2008 and 2018 | 1091 | 924 |

If a step removed far more people than seems right, or the topics are not the ones this record belongs to, the cohort is answering a different question and nothing above it holds.

## What is not here

Teaching, mentoring, service, funding, software, datasets, patents and public scholarship are absent from OpenAlex and are a large part of the job. See `docs/beyond-papers.md`.

Career start is estimated from publication bylines for everyone in the cohort. Lecturer-to-tenure-line conversions, clinical appointments, parental leave and delayed starts are invisible to it, and people who never changed institution are excluded because their trainee years cannot be told apart from their independent ones.

OpenAlex splits some people across profiles and merges others with namesakes. The cohort keeps only people it could identify confidently, which tilts it toward distinctive names.

Journal impact is a property of a journal and says nothing about an individual paper in it.

Cells covering fewer than 5 people are withheld, because a quartile over a handful of people can identify them.

`chaperone.md` asks a second question of the same cohort: when one of these papers reached a top-quartile venue, was the person leading it or co-authoring it? That page is also in `report.pdf`.

Method: `docs/methods.md`. Data: OpenAlex (Priem, Piwowar and Orr, 2022), CC0.
