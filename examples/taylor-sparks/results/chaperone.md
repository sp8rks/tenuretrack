# The chaperone effect in materials chemistry

For 1091 people in materials chemistry, through career year 6: when a paper reached a top-quartile venue, was this person leading it or co-authoring it?

Sekara et al. named the chaperone effect: for a great many researchers, the route into a selective venue runs through an established collaborator rather than through their own lab. A venue list on its own cannot tell the two routes apart. This page is what separates them, for one cohort and never for one person in it.

Led means last author, or flagged as the corresponding one. First author but not leading is the shape of a paper written inside somebody else's group. Middle is everything else. A paper counts on every side only if its venue has an impact figure.

The two readings below answer different questions and are both here because either one alone misleads. The pooled rate is dominated by whoever wrote the most papers. The paired comparison describes a typical person, and drops anyone without enough papers in both roles. Where they disagree, that disagreement is the finding. The same two readings are drawn as charts in `report.pdf`.

## Across every paper the cohort wrote

| Role | People | Papers | In top-quartile venues | Rate |
|---|---|---|---|---|
| Led (last or corresponding) | 1044 | 10566 | 2682 | 25.4% |
| First author, not leading | 885 | 3998 | 892 | 22.3% |
| Middle author | 1063 | 16488 | 4640 | 28.1% |

## The gap between not leading and leading

Middle-author rate minus led rate: 2.8% (95% confidence interval 0.6% to 5.0%), across 1090 people.

A positive number means the cohort's papers reached top-quartile venues more often when its members were not leading them. The interval comes from a cluster bootstrap that resamples people, so it says how far this would move with a different draw of people from the same subfield. An interval that spans zero has not settled the direction either way.

## The same people, compared against themselves

770 people had at least 3 papers with a resolvable venue in both roles. Every one of them is their own control here, so field, institution, career stage and how prolific someone is all cancel out.

| | Median within-person rate |
|---|---|
| Papers they led | 18.2% |
| Papers they did not lead | 25.0% |

393 of them reached top-quartile venues more often when not leading, 297 the other way, and 80 at the same rate in both roles. Sign test p = 0.000292.

## Where the cohort leads, and where it does not

The same journals the report lists, with the share of the cohort's papers in each that a cohort member led. A journal a subfield publishes in constantly but rarely leads in is a different kind of venue from one it leads in half the time.

| Venue | Cohort papers | Share the cohort led |
|---|---|---|
| Bulletin of the American Physical Society | 932 | 25.6% |
| Journal of Power Sources | 807 | 43.7% |
| Journal of Materials Chemistry A | 657 | 35.2% |
| ACS Applied Materials & Interfaces | 609 | 33.5% |
| Physical review. B./Physical review. B | 593 | 20.2% |
| Journal of Alloys and Compounds | 539 | 37.9% |
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

It is an approximation of their design and not a replication. They followed authors through time and modelled the sequence of a career. Here each person's window is a single snapshot and the comparison is across roles inside it. The direction of a difference is informative; its size should not be read against their figures.

Corresponding-author flags are missing for many journals and years, so last position carries most of the weight in deciding who led. Where a field does not order authors by contribution, none of this applies.

Nothing here says who should lead what. It is a description of how a group of papers was authored, and a piece of context for reading any one venue list, including the one in the report beside it.

Method: `docs/methods.md`. Data: OpenAlex (Priem, Piwowar and Orr, 2022), CC0.
