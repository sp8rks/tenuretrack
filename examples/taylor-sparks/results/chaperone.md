# Led versus co-authored papers in materials chemistry

For 1091 people in materials chemistry, through career year 6: when a paper reached a top-quartile venue, was this person leading it?

Roles follow the last-author convention. Led means last author or flagged corresponding author. First-author-not-leading is the shape of a paper written inside somebody else's group. Middle is everything else. Only papers whose venue has an impact figure are counted, on every side.

## Across all the cohort's papers

| Role | People | Papers | In top-quartile venues | Rate |
|---|---|---|---|---|
| Led (last or corresponding) | 1044 | 10566 | 2682 | 25.4% |
| First author, not leading | 885 | 3998 | 892 | 22.3% |
| Middle author | 1063 | 16488 | 4640 | 28.1% |

## Middle-author rate minus led rate

2.8% (95% CI 0.6% to 5.0%), across 1090 people.

A positive number means the cohort's papers reached top-quartile venues more often when its members were not leading them. The interval comes from a cluster bootstrap resampling people, so it describes how much this would move with a different draw of people from the same subfield.

## The same people, compared against themselves

770 people had at least 3 venue-resolvable papers in both roles.

| | Median within-person rate |
|---|---|
| Papers they led | 18.2% |
| Papers they did not lead | 25.0% |

393 reached top-quartile venues more often when not leading, 297 the other way, 80 the same. Sign test p = 0.0002924.

Every person here is their own control, so field, institution, career stage and how prolific someone is all cancel out.

## Where the cohort leads and where it does not

| Venue | Cohort papers | Share the cohort led |
|---|---|---|
| Bulletin of the American Physical Society | 932 | 25.6% |
| Journal of Power Sources | 807 | 43.7% |
| Journal of Materials Chemistry A | 657 | 35.2% |
| ACS Applied Materials & Interfaces | 609 | 33.5% |
| Physical review. B./Physical review. B | 593 | 20.2% |
| Journal of Alloys and Compounds | 539 | 37.8% |
| Chemistry of Materials | 515 | 36.1% |
| RSC Advances | 431 | 33.4% |
| Ceramics International | 403 | 44.7% |
| Electrochimica Acta | 387 | 43.7% |
| Journal of The Electrochemical Society | 373 | 26.5% |
| International Journal of Hydrogen Energy | 357 | 39.8% |
| Materials Science and Engineering C | 334 | 46.4% |
| The Journal of Physical Chemistry C | 324 | 31.5% |
| Advanced Energy Materials | 313 | 22.4% |

## What this is and is not

This follows Sekara, Deville, Andersen, Jones, Lehmann and Ahmadpoor, "The chaperone effect in scientific publishing", PNAS 2018 (doi 10.1073/pnas.1800471115), which found that a researcher's route into a prestigious venue often runs through a senior co-author.

It is an approximation of their design, not a replication. They followed authors through time and modelled the sequence of a career. Here each person's window is one snapshot and the comparison is across roles within it. The direction of a difference is informative; its size should not be read against their figures.

Corresponding-author flags are missing for many journals and years, so last position carries most of the weight in deciding who led. Where a field does not order authors by contribution, none of this applies.

The two readings above answer different questions. The pooled rate is dominated by whoever wrote the most papers; the paired comparison describes a typical person but drops anyone without papers in both roles. Where they disagree, that disagreement is the finding.

Method: `docs/methods.md`. Data: OpenAlex (Priem, Piwowar and Orr, 2022), CC0.
