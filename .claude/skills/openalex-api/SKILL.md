---
name: openalex-api
description: How to query the OpenAlex REST API correctly for author, work, source, and topic data. Use this whenever writing or modifying any code that talks to api.openalex.org, builds a filter string, paginates, caches responses, handles 429 quota errors, or resolves an ORCID, institution ROR, or topic ID. Also use it when debugging why a cohort pull returned too few or too many people.
---

# OpenAlex API

Base URL: `https://api.openalex.org`. Docs: https://docs.openalex.org. Everything is CC0.

## Politeness and quota

- Always append `mailto=<OPENALEX_MAILTO>` to every request. This puts you in the polite pool (faster, more reliable). Read it from the environment; never hardcode.
- Limits: 100,000 requests per day and 10 per second per mailto/IP. Shared-IP runners (GitHub Actions) get a far lower effective daily budget because the IP is shared. Prefer running large pulls locally.
- On 429, read `Retry-After`. If it exceeds 60 s, do not sleep; raise `QuotaExhausted` with the reset time. The caller writes partial results and exits nonzero. A daily quota resets at midnight UTC.
- Retry 5xx with exponential backoff, max 5 tries.

## Caching

Cache every GET on disk under `.cache/<sha256 of method+url+params>.json`. Cache hits never touch the network. This makes reruns free and quota-killed runs resumable. Never commit `.cache/`.

## Pagination

Use cursor pagination for anything that might exceed a page: `per-page=200&cursor=*`, then follow `meta.next_cursor` until it is null. Do not use `page=` beyond 10,000 results (it is capped).

Use `select=` to trim fields and shrink responses, e.g. `select=id,display_name,orcid,affiliations,topics,summary_stats,works_count`.

## Entities you need

### Authors (`/authors`)
Fields: `id` (A...), `display_name`, `display_name_alternatives`, `orcid`, `affiliations[]` (each with `institution.id/ror/display_name/country_code/type` and `years[]`), `last_known_institutions[]`, `topics[]` (with `count` and `share`), `summary_stats` (`h_index`, `i10_index`, `2yr_mean_citedness`), `works_count`, `cited_by_count`, `works_api_url`.

Useful filters:
- `filter=orcid:0000-0000-0000-0000` to resolve a subject.
- `filter=topics.id:T10001|T10002,affiliations.institution.country_code:US,affiliations.institution.type:education` for a candidate pool. Note: `|` is OR within a filter, `,` is AND across filters.
- `filter=works_count:>10` to drop trivial profiles early.
- `search=Jane Doe` for name lookup (last resort; prefer ORCID).

### Works (`/works`)
Fields: `id`, `doi`, `title`, `publication_year`, `type` (keep `article`; drop `preprint`, `editorial`, `letter`, `erratum`, `paratext`, `book-chapter` unless configured), `authorships[]` (each with `author.id`, `author_position` = first/middle/last, `is_corresponding`, `institutions[]`), `primary_location.source` (`id`, `display_name`, `issn_l`, `is_in_doaj`), `primary_topic`, `topics[]`, `cited_by_count`, `counts_by_year[]`.

Useful filters:
- `filter=authorships.author.id:A1234567,publication_year:2021-2026` for one person's papers.
- `filter=authorships.author.id:A1234567,authorships.institutions.ror:https://ror.org/xxxx` to anchor to an institution byline.
- `filter=type:article` to restrict article type.

### Sources (`/sources`)
`summary_stats.2yr_mean_citedness` is the impact-factor analogue used for venue impact. Fetch once per distinct source ID and cache. `is_in_doaj`, `type` (journal vs repository), `host_organization` are useful for filtering out preprint servers.

### Topics (`/topics`)
IDs look like `T10123`. Each has `display_name`, `subfield`, `field`, `domain`, and `works_count`. Use `/topics?search=...` to find IDs by name when the user edits their yaml with a name instead of an ID.

### Institutions (`/institutions`)
Resolve a ROR from a name with `/institutions?search=University of Utah` and confirm with the user. Store the full ROR URL (`https://ror.org/03r0ha626`), which is the form the works filter expects.

## Known data quirks

- One person is often split across several author IDs (name changes, stray profiles with 1 to 3 works). Union by DOI when the split profiles share an institution and topics; never union two profiles that both have substantial output.
- Common names collide with people in other fields. A profile whose topics are 40% outside your subfield is probably two people.
- `is_corresponding` is under-recorded for many journals and years. Treat last-author position as the robust "led" signal; corresponding flag is a bonus.
- `affiliations[].years` is derived from paper bylines, so a gap year is not evidence of leaving.
- `counts_by_year` only goes back about 10 years; for older citation histories use `cited_by_count` on the works themselves.

## Sizing a pull

A subfield pull is typically: 1 subject author + 1 subject works page, then 3,000 to 15,000 candidate authors (15 to 75 pages), then one works query per surviving candidate (a few hundred to a few thousand requests), then one source lookup per distinct venue (a few hundred). Budget 2,000 to 10,000 requests per subject. Print the running request count.
