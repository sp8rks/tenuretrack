---
name: deck-builder
description: The six-slide report format for a subject-vs-cohort tenure benchmark. Use this whenever building, editing, or restyling slides, figures, or the PPTX export, and when someone asks for "the deck", "slides", "a one-pager", or a shareable version of the results. Uses python-pptx and matplotlib; exports PDF via LibreOffice when available.
---

# Deck builder

Six slides, 16:9, one idea each. Every number on a slide is read from `results/` files produced by the pipeline, never typed in, so the deck and the report cannot disagree. Run the aggregates-only guardrail on all slide text before saving.

## Slides

1. **Title.** Subject name, institution, subfield label (the topic set in plain words), career year, cohort size and institution count, date generated, OpenAlex attribution.
2. **How the cohort was built.** The funnel as a horizontal bar chart (candidates, core-topic share, university, fresh start in window, PI-like headline) with the topic list and the top 8 contributing institutions (counts of 5 or more only, rest bucketed). One sentence on what the cohort is and is not.
3. **Subfield norms through year 6.** Table: metric, p25, median, p75 (with CI in a small font under each). Rows: publications, led publications, lead share, citations, h-index, median venue impact, top-quartile venue share. Footnote: citations are as of today for papers 8 to 18 years old.
4. **Subject vs cohort at the same point on the clock.** Dot-and-range chart: for each metric, cohort p25-p75 band with median tick, subject's value as a dot. Horizon = subject's current career year (or 6 if past it). Citations row shown for the subject with "not compared" in place of the band. Position words under the chart follow the cohort-methodology skill.
5. **Venues.** Left: the cohort's top 12 venues by window paper count with impact values, top-quartile bar marked. Right: the subject's window venues. Optional third panel when the chaperone report exists: top-quartile rate by authorship role.
6. **Caveats.** Fixed items (identity matching drops ambiguous names, corresponding-author under-recording, venue impact is journal-level, career start is estimated for the cohort) plus subject-specific items the pipeline flags (small n, mixed communities in the topic set, clock start assumptions, byline-anchoring exclusions).

## Style

- One typeface, dark text on white, a single accent color for the subject's dot. No clip art, no gradients.
- Charts via matplotlib saved at 200 dpi PNG and placed with python-pptx; keep chart code in `tenuretrack/figures.py` so the Markdown report can reuse the same PNGs.
- No em-dashes anywhere in slide text.
- Speaker notes on slides 3 and 4 restate the comparison rules in one sentence each.

## Export

`tenuretrack slides` writes `results/<subject-slug>.pptx`. If `soffice` is on PATH, also write `results/<subject-slug>.pdf` with `soffice --headless --convert-to pdf`. If not, print one line saying PDF export was skipped and how to enable it. Never install LibreOffice inside the run.
