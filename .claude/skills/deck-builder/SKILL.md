---
name: deck-builder
description: The slide format for a subject-vs-cohort tenure benchmark. Use this whenever building, editing, or restyling slides, figures, or the PPTX export, and when someone asks for "the deck", "slides", "a one-pager", or a shareable version of the results. Uses python-pptx and matplotlib; exports PDF via LibreOffice when available.
---

# Deck builder

Eight slides, 16:9, one idea each. Every number on a slide is read from `results/` files produced by the pipeline, never typed in, so the deck and the report cannot disagree. Run the aggregates-only guardrail on all slide text before saving.

This deck is the artifact most likely to be forwarded to a committee and read without its author in the room. Design for that reader: someone scanning eight slides in two minutes, who will believe whatever the layout implies.

## Layout system

Every content slide uses the same frame, so the eye lands in the same place and only the content moves. Fixed positions, in inches on a 13.333 x 7.5 slide:

| Element | Top | Notes |
|---|---|---|
| Kicker | 0.40 | 9pt bold, accent colour, uppercase, e.g. `3. THE COHORT AT YEAR 6` |
| Title | 0.62 | 25pt bold ink |
| Accent rule | 1.22 | 0.86in wide, 0.035in thick |
| Takeaway | 1.34 | 13.5pt muted, one sentence saying what to see |
| Content | 1.92 | 4.62in tall, full 12.09in width |
| Slide note | 6.30 | 9.5pt muted, the one caveat belonging to this slide |
| Footer rule | 6.78 | hairline, full width |
| Footer | 6.86 | 8.5pt muted: subject, subfield, cohort size, "aggregates only"; slide number right |

Margin is 0.62in on both sides. Content is either full width, or a chart plus a tinted side panel with a 0.42in gutter.

**Every content slide carries a takeaway.** A chart that depends on narration arrives silent when the deck is forwarded. Say the point in words, descriptively.

## Slides

1. **Title.** Accent bar down the left edge. Subject name at 40pt, subfield and institution, the subject's own career year and the comparison year, four stat tiles (cohort size, comparison year, cohort start window, topic count) matching the report's cover, the "not a standard" paragraph, date and OpenAlex attribution, and the logo in the top right corner, on this slide alone: repeated on all eight it would read as furniture rather than as attribution. `branding.logo_path` returns None on an install without the asset, and every caller draws nothing rather than failing.
2. **Where this record sits.** One row per metric: a band from cohort p25 to p75 drawn the same length whatever the units, median tick, subject diamond, quartile figures above the band and the position words to the right. Citations get a band and no diamond. Rows, not per-metric panels: panels on their own vertical scales give no shared baseline.
3. **Year by year.** Small multiples, one panel per metric, p25-to-p75 ribbon and median across every career year, subject marked at the horizon. Uses the quartiles the pipeline already computes at every year.
4. **The cohort's numbers.** Table at the comparison horizon, p25 / median / p75 with the bootstrap interval under each figure in smaller muted type, plus a "how to read a row" side panel.
5. **How the cohort was built.** Funnel on a log x-axis with the share of the step above that each filter kept, plus a side panel naming the topics and what the cohort is and is not.
6. **Venues.** The busiest venues by window paper count with impact in brackets, top-quartile ones in the cohort colour, and a second panel giving the share of each venue's papers the cohort led.
7. **The chaperone effect.** Pooled top-quartile rate by role beside the paired within-person medians, with the gap and its interval stated in words. The takeaway names the effect and says what it is, because a reader who has not read Sekara et al. cannot read two bar charts of roles without it. Omitted entirely when the chaperone pass has not run.
8. **What this cannot see.** Six limits in two columns, each an accent tick, a bold claim and a muted sentence, closing on a panel pointing at `docs/methods.md` and `results/`.

## Style

- One typeface. Dark text on white. Accent colour only for the subject's own value and for structural marks (kicker, rules). Cohort blue for the cohort's own numbers.
- Palette lives in `tenuretrack/figures.py` (`ACCENT`, `BAND`, `COHORT`, `INK`, `MUTED`, `PANEL`, `RIBBON`, `RULE`) and is shared with the PDF report. Do not define a colour in the slide builder.
- **No stock chrome.** Turn off `shape.shadow.inherit`, set `table.first_row = False` and `table.horz_banding = False`, and write cell borders by hand: header top and row bottoms only, never left or right. An inherited grid makes a result look like a spreadsheet.
- Tables: tinted header, alternating row fills, labels left, numbers right, intervals on a second line at 1.5pt smaller in muted grey.
- Charts via matplotlib at 200 dpi, drawn at the aspect of the box they land in, and placed with a helper that preserves aspect rather than stretching to fit. Chart type sizes run several points larger than the report's, because a deck is read from the back of a room.
- Keep chart code in `tenuretrack/figures.py` so the report can reuse the same PNGs.
- No em-dashes anywhere in slide text.
- Speaker notes on the comparison slides restate the comparison rules in one sentence.

## Export

`tenuretrack slides` writes `results/<subject-slug>.pptx`. If `soffice` is on PATH, also write `results/<subject-slug>.pdf` with `soffice --headless --convert-to pdf`. If not, print one line saying PDF export was skipped and how to enable it. Never install LibreOffice inside the run.

`results/report.pdf` is a separate artifact built by `tenuretrack/pdf_report.py` with matplotlib alone, because the no-install Colab path cannot install LibreOffice. The two share a palette and a page structure on purpose; a reader who sees one after the other should not have to work out whether they are about the same thing.
