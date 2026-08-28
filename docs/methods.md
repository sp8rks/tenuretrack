# Methods

This document is the authoritative description of how a cohort is built and how numbers are computed. The code implements exactly this; when the code changes, this file changes in the same pull request.

## 1. The question

At the same point on the tenure clock, what does the publication record of an early-career faculty member in a given subfield typically look like, and where does one specific person sit relative to that distribution?

"Typically" means quartiles across a cohort, never a single expectation. "Subfield" means a small set of OpenAlex topics chosen from the subject's own papers.

## 2. Data source

All data is from OpenAlex (CC0). Author records give affiliations by year and topic shares; work records give authorship positions, venue, year, and citations; source records give venue impact (`2yr_mean_citedness`). Nothing is scraped from university websites.

## 3. Subject

The subject supplies an ORCID, an institution (a name or a ROR), and the first calendar year of the tenure-line appointment. Career year is `publication_year - start_year + 1`.

### 3.1 Identity

The ORCID resolves to one OpenAlex author record. OpenAlex sometimes splits one person across several author IDs, so `init` also searches for author profiles at the same institution whose name matches, and merges a candidate only when every one of these holds:

- It is not the primary profile.
- It carries no ORCID of its own, or carries the same one. A profile with a different ORCID is a different person.
- A name key matches, comparing surname plus first initial across the display name and every `display_name_alternatives` entry, with accents and suffixes stripped.
- It has at least one work, at most 10, and no more than half the primary profile's work count. Two profiles that both carry substantial output are two people until proven otherwise.
- It lists the institution among its affiliations.
- It shares at least one topic with the primary profile, which keeps a namesake in another field out.

Works from the merged profiles are unioned by DOI, or by normalized title plus year when a DOI is missing. The merged IDs are written into `benchmark.yaml` so the run is reproducible and so the subject can see what was merged.

### 3.2 Window

The subject's window papers are journal articles (the shared `article_types` rule, preprint servers excluded) in career years 1 through N carrying the institution's byline. Papers from eight years before the appointment are fetched as well: they are outside the window, and they are what the career-start rules in section 5 read.

### 3.3 Topics

Topics are proposed from the window papers and confirmed by the subject before any cohort is built. Each paper votes once, for its OpenAlex `primary_topic`; counting every listed topic would let one paper vote five times. Topics are ranked by how many of the subject's papers sit in each, and each proposal is shown with the venues those papers ran in, so the subject can see what a topic actually represents in their record.

A topic carrying fewer than three of the subject's papers is not proposed. If that leaves fewer than four topics, the count relaxes to two and the printout says the record is thin. Four to six topics is the working range, and six is the ceiling.

Someone one or two years into the clock may have almost nothing published under the new byline yet, which is too thin to name a subfield from. When the institution-anchored set holds fewer than five papers, the proposal widens, first to every article published since the appointment began regardless of byline, then to the whole publication record. Widening never happens silently: the basis is printed with the proposal. Only the topic proposal widens. The window itself, and every number computed from it, stays anchored on the institution byline.

## 4. Cohort funnel

| Step | Rule | Default |
|---|---|---|
| Candidates | Authors with any of the topics, at least 10 works, affiliation in the configured countries, excluding the subject | US |
| Core-topic share | Sum of topic shares over the configured topics | at least 0.4 |
| University | At least one `education` affiliation | |
| Plausible years | Byline years could contain a start inside the window | |
| Career start | A confident first independent start could be estimated | |
| Start in window | That estimate falls inside the cohort window | 2008 to 2018 |
| PI-like | At least 3 led journal articles in the window, activity in at least 2 distinct window years | |
| Identity | Profile does not look merged or fragmented | |

The subject is removed from their own pool: a distribution someone is being placed against should not contain them. The pool itself comes from one OpenAlex author query: any of the configured topics, more than nine works, and at least one affiliation in the configured countries. It is streamed to `data/pool.jsonl.gz` as it arrives, one person per line, and written through a temporary file so a file that exists is a file that finished. A pool holds names, so `data/` is never committed.

The core-topic share is the main lever on cohort size, and the default is set from a measurement rather than from taste. On a six-topic materials-science subject, a pool of 82,601 US authors left 27,409 people at a share of 0.25, 4,738 at 0.4, and 836 at 0.5. A share of 0.25 admits anyone who does a quarter of their work in the subfield, which is most of a discipline rather than a peer group, and it makes the per-candidate stages that follow cost hours. Raise it for a tighter cohort, lower it for a broader one, and read the funnel to see what the change did.

The country rule is applied twice, once in the query and once locally, because a pool gathered under one config can be re-screened under another without refetching. The core-topic share is derived from the work counts on the author's topics. OpenAlex does not publish a per-author topic share: entries under `topics` carry `count` and no share, and the separate `topic_share` field is a different quantity, the author's share of that topic's global output, which for one person sums to about 0.001. Using it here would be a category error. The code reads a `share` field if one ever appears and falls back to counts, which is the path that runs today.

Counts after every step are written to `results/funnel.csv`, with columns `step,label,rule,kept,dropped`. That file carries counts and rule text and nothing else, and the guardrail runs on it before it is returned. Cohorts under 40 people carry a warning.

## 5. Career start estimation

The subject's start year is supplied and trusted. Every cohort member's is inferred from bylines, and this is the weakest link in the method: a wrong start year moves someone to the wrong career year and corrupts the norms without any visible symptom. The rule is therefore strict, and anyone it cannot place confidently is dropped and counted rather than guessed at.

### 5.1 What OpenAlex does not have

The authoritative signal would be an employment record. OpenAlex does not carry one. An author record has `affiliations`, whose years are derived from paper bylines, and `last_known_institutions`; there is no appointment, title, or employment field. This was checked against the live API. So the rule below works entirely from bylines, and the tool does not claim an employment-record rule it cannot run.

### 5.2 The rule

Over the person's journal articles, each paper is classified by their role (led, first-not-led, middle) and by the institutions they carried on it.

**Rule 2, high confidence.** First decide which institutions look like independent posts. An institution qualifies when it holds at least two of the person's led papers *and* at least a fifth of however many they led at their strongest post. Then order the qualifying institutions by the first year the person carried that byline and take the earliest: someone who moved between two faculty jobs started at the first one. Accept it only when some earlier institution was not itself a qualifying post. That earlier institution is the PhD or postdoc, and its presence is what distinguishes an independent start from a continuation.

Both halves of that come from a measured failure. A flat two-paper bar treats a stray affiliation as equal evidence to a career: one subject with 71 led papers at his university also carried two at a nearby medical centre, and the flat rule dated his start from the medical centre. Judging each institution against the person's own strongest post fixes it without an absolute number, which would not travel between fields. And requiring the earlier institution to have *no* led papers was too brittle, because a single last-author paper during a PhD disqualified the correct answer; what matters is that the earlier place was not itself a post.

**Rule 3, low confidence.** The first led paper minus one. It exists so the funnel can distinguish people who were placed weakly from people who could not be placed at all. Low-confidence estimates never enter the cohort.

Two papers is the floor for "runs a group" because one led paper is a fluke of author ordering. The requirement for an earlier non-post institution is what refuses the ambiguous case: a person whose entire record sits at one institution might be a faculty member who never moved, or a student who stayed, and bylines cannot tell those apart.

### 5.3 Known failure modes

A postdoc who published two led papers before starting their faculty job at the same institution gets an estimate that is too early. A person who moved from a short first faculty job to a much more productive second one can have the first job fall below the one-fifth share and be dated from the second, which is the cost of the rule that keeps stray affiliations out. The start year is the first byline year at the institution, and papers lag appointments, so an estimate can sit a year late. A person whose PhD institution is missing from OpenAlex bylines is dropped as ambiguous rather than misplaced, which is the intended direction. People who never moved institution are systematically excluded, which biases the cohort toward the mobile.

### 5.4 Cost

Estimating a start needs the person's papers, which is the most expensive stage in the pipeline. Works are requested fifty authors at a time, so the request count tracks the number of pages the results fill rather than the number of people. Before any request, candidates whose byline years could not contain a start inside the window are dropped: that pre-filter only removes people whose rule-2 estimate could not land in the window anyway, so it saves requests without changing who ends up in the cohort.

The cohort window (2008 to 2018) guarantees every member has completed at least six career years by the time of analysis.

## 6. Metrics

Computed per person through career year N, for N = 1..6 and for the subject's current career year. Career year 1 is the calendar year the appointment began, so the window through year N runs from `start_year` to `start_year + N - 1` inclusive.

- **Publications.** Journal articles only: OpenAlex `type == "article"`, not on a preprint server. Applied identically to the subject and to every cohort member, because a comparison where one side counts preprints is not a comparison.
- **Led publications.** Last author, or corresponding author where the flag is set. Corresponding flags are missing for many journal-years, so last position is the robust signal and the flag is a bonus. Lead share is led divided by publications.
- **Citations.** Sum of `cited_by_count` over window papers, as they stand today.
- **h-index** over window papers only, not the person's whole record.
- **Median venue impact** over window papers whose venue has a `2yr_mean_citedness` figure.
- **Top-quartile venue share**: the fraction of venue-resolvable window papers at or above the cutoff in 6.2.

Cohort members count every byline. Their start estimate already anchored them to an institution, and filtering again on that institution would drop the papers they wrote after moving. The subject is anchored to `institution_ror`, because for them the question is what they did in this job.

### 6.1 What stays missing

A venue with no impact figure is left out of the venue calculations rather than counted as zero. Imputing would invent numbers for exactly the venues OpenAlex knows least about, which are disproportionately the smaller and newer journals, and would drag a person's median toward whatever value was chosen.

A share over zero papers is recorded as missing, not as zero. Someone with nothing published in year 1 has no lead share; entering a zero would mix "led none of them" with "had none to lead" and pull the cohort's quartiles down with a value that means "not applicable". Each quartile reports how many people actually had a value.

### 6.2 The top-quartile cutoff

The cutoff is the 75th percentile of venue impact across every headline-window paper the cohort wrote, computed once and then held fixed across all horizons.

Within the cohort, never from a global journal list: a first-quartile journal in one subfield is a fourth-quartile journal in another, and describing this subfield is the whole point.

Fixed across horizons because a cutoff recomputed at each N would move under the comparison. "Top quartile at year 3" and "top quartile at year 6" would then be different questions, and the report puts them in the same table.

## 7. Quartiles and uncertainty

p25, p50 and p75 per metric and horizon, taken across people. Never a mean: a mean publication count is pulled around by the top of the distribution and describes nobody.

95% confidence intervals come from a cluster bootstrap that resamples people, 2,000 iterations by default. People, not papers, because the thing that varies between imaginable cohorts is which people are in them. Resampling papers in a cohort where one prolific member wrote a fifth of them would report that member's habits as the subfield's norm.

Cells covering fewer than `min_cell_size` people (default 5) are withheld from both output files. The count is still published; only the values are suppressed. A quartile over a handful of people can identify them.

Outputs are `results/benchmarks.csv` and `results/benchmarks.md`. Both writers run the aggregates-only guardrail on the finished file before returning.

## 8. Comparison rules

- Compare only at matching career years.
- Citations are reported for the subject but never compared: cohort window papers are 8 to 18 years old, the subject's are 0 to N.
- Positions are stated as quartile locations, not judgments.

## 9. Chaperone analysis

Each headline-cohort window paper is classified by the member's role: led (last author or flagged corresponding), first-not-led, or middle. Only papers whose venue has an impact figure are counted, on every side: including papers whose venue cannot be placed would make the rate track OpenAlex's venue coverage, which differs systematically by role.

Two readings are reported, because either alone misleads.

**Pooled across papers.** The top-quartile rate per role over every window paper in the cohort, with a cluster-bootstrap 95% CI on the middle-minus-led gap, resampling people. This answers "across this subfield's output", and is dominated by whoever published most.

**Paired within person.** For everyone with at least 3 venue-resolvable papers in both the led and middle classes, the within-person top-quartile share in each class, the median of each, and a two-sided sign test on which direction each person went. This answers "for a typical person", and removes field, institution, career stage and productivity at once because each person is their own control. Below three papers a single paper flips a person's share from 0 to 1 and the test starts counting coin flips.

Where the two disagree, the disagreement is the finding and the report says so.

A per-venue table gives the share of the cohort's papers at each of the busiest venues that the cohort led, which names venues and never people.

This approximates, cross-sectionally, the longitudinal design of Sekara, Deville, Andersen, Jones, Lehmann and Ahmadpoor, "The chaperone effect in scientific publishing", PNAS 2018 (doi 10.1073/pnas.1800471115). They followed authors through time and modelled the sequence of a career; here each person's window is one snapshot and the comparison is across roles within it. The direction of a difference is informative, its size is not comparable to theirs.

Measured on one subfield cohort of 1,091: pooled top-quartile rate 25.4% on led papers and 28.1% on middle-author papers, a gap of 2.8% (95% CI 0.6% to 5.0%). Within person, across the 770 people with enough papers in both classes, the median rate was 18.2% on papers they led and 25.0% on papers they did not, with 393 people higher when not leading against 297 the other way (sign test p = 0.0003). Both readings point the same way.

## 10. Known limitations

- Name disambiguation in OpenAlex is imperfect; the conservative identity filter biases the cohort toward distinctive names.
- Corresponding-author flags are missing for many journal-years; last-author position is the robust signal.
- Venue impact is journal-level and field-dependent; the within-cohort quartile comparison partly corrects for this, but a topic set that spans two citation cultures will show it.
- Some conference abstract series carry an ISSN and are typed as `journal` by OpenAlex, with `is_core` sometimes set, so no field distinguishes them from a real journal. Their entries are typed `article` and are therefore counted as publications on both sides of every comparison. Measured: `Bulletin of the American Physical Society` supplied 932 of one cohort's 122,111 window papers and sat at the top of the venue table with an impact of 0.00. The venue table is printed in full partly so a reader can see this, and a venue near the top with an impact near zero is usually an abstract series.
- Career start is estimated from bylines for cohort members. Lecturer-to-tenure-line conversions, clinical appointments, and delayed starts are invisible.
- Conference papers, book chapters, software, datasets, patents, teaching, and outreach are outside the data. See `beyond-papers.md`.
