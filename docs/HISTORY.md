# Development timeline

Biz Intel began as a small business-record pipeline and grew into a reusable,
evidence-first research workspace. This timeline summarizes milestones from
the original development commits.

The public repository received a consolidated snapshot in October 2026. Earlier
work took place on a private working branch that also contained local project
notes and research records, so that branch's full history was not published.

## July 2026 — Pipeline foundation

- Created the business data model and initial project structure.
- Added browser actions, extraction, and a bounded Yellow Pages source.
- Added CSV ingestion, normalization, validation, and deduplication.
- Introduced shared pipeline stages, metrics, and regression tests.
- Added versioned YAML jobs, source-task planning, manifests, and CSV/JSON
  export.
- Added API and provider boundaries for Yelp, Google Places, and Apify.

## August 2026 — Limits and operating controls

- Added source-local pagination limits.
- Added per-source enrichment ceilings and run cost reporting.
- Documented the first delivery and development roadmap.

## September 2026 — Evidence and repeatable runs

- Added source policies, first-party website enrichment, field provenance, and
  delivery acceptance rules.
- Added offline fixture controls and source-specific cache retention.
- Added resumable jobs, progress reporting, grouped run artifacts, and the
  command-line runner.
- Added bounded NPPES acquisition and the San Jose dentist pilot.
- Added conservative fuzzy deduplication and an optional phone-verification
  pilot.

## Early October 2026 — Source composition

- Added typed claims and conservative cross-source matching.
- Added Washington contractor and California dental-board evidence sources.
- Added local Overture snapshots and account-scoped credential loading.
- Added a bounded LinkedIn/Apify adapter and clarified source-policy boundaries.

## October 11–20, 2026 — Research sessions and plugins

- Added reusable research sessions so later questions continue from saved
  businesses instead of repeating candidate acquisition.
- Added session listing, selection, JSON preview, summaries, audits, and export.
- Added plain-language compound refinements for Medi-Cal enrollment, ownership,
  business longevity, operational status, public email, and social profiles.
- Added reviewed-result composition with identifier-first matching and explicit
  ambiguous outcomes.
- Added bounded first-party crawling with robots, TLS, DNS, timeout, redirect,
  connection, and HTTP outcomes.
- Added Overture snapshot preparation and review queues without treating
  candidates as automatically approved evidence.

## October 20, 2026 — Public WIP snapshot

- Reframed the public project around reusable business research.
- Split detailed guidance into plugin, job, session, source-policy, and cookbook
  documents.
- Removed local notes, working research data, screenshots, and machine-specific
  output from the public tree.
- Published the current implementation as a clean work-in-progress snapshot.
