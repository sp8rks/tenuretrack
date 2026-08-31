# tenuretrack

**Nobody tells assistant professors the numbers. This tool computes them.**

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/sp8rks/tenuretrack/blob/main/notebooks/tenuretrack_colab.ipynb)

**Run it in your browser.** No install, no Python. Open the notebook, type your
ORCID, your university, your start year and your email, and run the cells from
the top. It builds your cohort on a temporary Google machine and hands you a PDF
report and a zip. Grab a [free OpenAlex API key](https://openalex.org/settings/api)
first: it takes thirty seconds, costs nothing, and turns a three-day run into a
forty-minute one.

Every assistant professor goes up for tenure. Almost none of them are told what a typical record looks like: how many papers, how many led from their own group, what venues, what h-index, by year six. Departments have opinions. Senior colleagues have anecdotes. The actual distribution is knowable, and this tool computes it from open data.

Give it your ORCID, your institution, and your start year. It builds a cohort of early-career faculty in your subfield from [OpenAlex](https://openalex.org), computes publication norms through each year of the tenure clock, and shows where you sit at the same point on the clock. Aggregates only. No names, no rankings, no per-person tables.

## What you get

`results/report.pdf` is the thing to open: the whole report with the charts, the funnel and the limits in one document. Beside it are the same numbers as Markdown and CSV, and a six-slide PPTX for anyone who has to present them.

- **Where your record sits** at the same career year as the cohort, each measure against the cohort's middle half
- **Year by year**: the cohort's p25/median/p75 at the end of every year of the clock, not only at year six, so the numbers mean something in year two as well
- **Subfield norms** (p25 / median / p75, with cluster-bootstrap confidence intervals): publications, lead-author publications, lead share, citations, h-index, median venue impact, share of papers in top-quartile venues
- **Citations shown and never placed**: your papers have had 0 to N years to accrue them and the cohort's have had 8 to 18, so a comparison would measure the calendar
- **Funnel transparency**: every filter, how many people it left, and what share of the step above that was
- **Venue list**: the journals your subfield actually publishes in, with impact values, so "Q1" means Q1 in your field and not someone else's, and how much of the work in each one the cohort led
- **Chaperone analysis** (optional): whether the cohort's flagship-venue papers are led from their own groups or co-authored on senior colleagues' papers, pooled and again within each person

## Quick start, in your browser

[Open the notebook in Colab](https://colab.research.google.com/github/sp8rks/tenuretrack/blob/main/notebooks/tenuretrack_colab.ipynb).
It installs the tool on a temporary Google machine, builds your cohort,
shows the report inline, and hands you a zip of everything. See
[notebooks/](notebooks/) for what each cell does.

**The API key matters.** Without one OpenAlex gives you roughly 1,000 requests a
day, and a cohort build spends a few thousand, so the run stops each day and
resumes the next: two or three days instead of forty minutes. The key is free,
needs no payment details, and is the single thing that most changes how this
feels to use. Get one at [openalex.org/settings/api](https://openalex.org/settings/api).

## Quick start, on your own machine

```bash
pip install git+https://github.com/sp8rks/tenuretrack.git
export OPENALEX_MAILTO=you@university.edu   # required, keeps you in the OpenAlex polite pool
export OPENALEX_API_KEY=your-free-key       # openalex.org/settings/api, 10x the daily allowance

tenuretrack init --orcid 0000-0000-0000-0000 --institution "University of X" --start 2021
# suggests subfield topics from your own papers, writes benchmark.yaml for you to edit

tenuretrack run
# builds the cohort, computes norms, writes results/
```

Everything is cached locally so reruns are free. A first run pulls a few thousand author records and takes 10 to 40 minutes depending on the size of your field, with a key. Without one it spends the day's allowance, stops, and resumes on the next run, so allow two or three days.

## How the cohort is built

1. **Topics.** Up to three OpenAlex topics define the subfield. The tool proposes them from your own recent papers; you confirm or edit them. This is the single most important choice you make, and the report shows you the top venues and institutions so you can sanity-check it.
2. **Candidates.** All authors with substantial work in those topics, filtered to US academia (configurable), with a core-topic share of at least 40%.
3. **Peers, if you want them.** `peer_group_size` narrows the cohort to the institutions closest to yours in subfield output, for a "schools like mine" comparison. Off by default. It costs people fast: a cohort averages under two per institution, so 15 schools leaves a group too thin for quartiles and the run says so.
4. **Tenure-track-shaped start.** People whose publication record shows a fresh independent start (first affiliation-anchored, lead-author papers) in the cohort window: by default the ten years either side of your own start year, so the cohort was publishing under roughly the conventions you were, with the recent end held back far enough that everyone in it has completed at least six years.
5. **PI-like headline cohort.** High-confidence matches only. Ambiguous names and people with split OpenAlex profiles are dropped rather than guessed at.
6. **Metrics through year N** for each cohort member, then quartiles with cluster-bootstrap confidence intervals.

The full filtering rules are in [docs/methods.md](docs/methods.md).

## What this is not

- **Not a threshold.** These are descriptive ranges of what people in a field have done, not what anyone should do. A department that turns the median into a quota has misread this tool.
- **Not a ranking of people.** Cohort members are real early-career faculty. The tool never writes their names or individual metrics to any output file. A `--show-cohort` flag prints names to your terminal for your own sanity check, and nothing else.
- **Not the whole job.** Teaching, mentoring, service, funding, code, datasets, and public scholarship do not appear in OpenAlex. See [docs/beyond-papers.md](docs/beyond-papers.md) for an argument about what tenure evaluation should also have space for.

## Known limitations

- OpenAlex splits some people across profiles and merges others with namesakes. High-confidence matching drops the ambiguous cases, which biases the cohort slightly toward people with distinctive names.
- Corresponding-author flags are under-recorded for some journals and years. Last-author position is the robust "led" signal.
- Impact values are journal-level, and different subfields have very different citation cultures. That is why venue quartiles are computed within your cohort's venue list, not globally.
- Career start is inferred from publication patterns, not from HR records. For your own record you supply the start year; for the cohort it is estimated.

## Data and privacy

- Your `OPENALEX_MAILTO` is sent to OpenAlex only, as their API asks.
- The local cache (`.cache/`) contains OpenAlex responses including author names. It is gitignored. Do not commit it.
- Results directories contain aggregates only and are safe to share.

## Building or contributing

This repo is built with Claude Code. Start with `CLAUDE.md`, then `TASKS.md` (one task per PR), and the skills in `.claude/skills/`. One worked example lives in `examples/`.

## Citing

If this shaped an RPT discussion or a paper, cite the repo (CITATION.cff) and OpenAlex (Priem, Piwowar, and Orr, 2022). The chaperone analysis is a cross-sectional approximation of Sekara et al., *PNAS* 2018 (doi 10.1073/pnas.1800471115).

## License

MIT. Cohort data comes from OpenAlex under CC0.
