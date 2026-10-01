# Biz Intel

A policy-gated pipeline for turning business records into clean, auditable
client exports. It normalises canonical records, can enrich them using permitted
content from public first-party business websites, and exports only the fields
requested by the client.

Biz Intel is not designed to bypass source restrictions. Before a source can
participate in a client-delivery run, it must have an explicit, approved policy
covering delivery rights, export use, retention, test fixtures, rate limits,
and cost.

In this repository, **approved** means that the person or team operating Biz
Intel has reviewed a source and the client's intended use, then encoded the
result in that source's `SourcePolicy`. The software enforces that decision; it
does not decide that a dataset is lawful to use or grant anyone data rights.

### Is this a scraper?

Not as a general-purpose, ready-to-run scraper. The client-delivery inputs
currently enabled are:

- an imported CSV containing actual business records, such as a small seed
  list to enrich or the output of an earlier run to reprocess; and
- the public CMS NPPES registry, for a narrow set of provider identity,
  practice-location, and practice-phone fields.

A sample CSV that only demonstrates the desired output shape is different from
a seed list. The current job format does not infer an output schema from sample
rows; requested output columns are declared explicitly in the job YAML. When a
CSV contains real seed records, Biz Intel can preserve those records and fill
available fields such as public website contact details and social links. When
the goal is to append newly discovered businesses, those additional rows must
come from an enabled acquisition source.

After a record has an authorized source and a business website, optional
enrichment can crawl that business's own public site within its robots policy
and bounded same-site page limits. Google, Yelp, Yellow Pages, and third-party
Apify connectors exist in the codebase, but they are disabled for client
delivery pending source-specific review. If you need an unrestricted directory
or marketplace scraper, this project does not provide one out of the box.

---

## How it works

```text
Job YAML (what is wanted)
        |
        v
   Planner → SourceTask list
        |
        v
  SourceRegistry → executor per source kind
        |
        v
  Business records (raw, per source)
        |
        v
  Validation → Normalization → Deduplication
        |
        v
  EnrichmentRunner (post-dedup, cache-aware)
  ├── ContactEnricher  phone + website via API, DuckDB cache; approved cap
  └── SocialEnricher   LinkedIn / Instagram / Facebook / Twitter from website crawl
        |
        v
  PhoneVerificationRunner (optional Twilio Lookup Basic, Keychain-backed)
        |
        v
  Delivery contract (`standard`) → accepted main export + quality/evidence sidecars
        |
        v
  RunResult manifest
```

Each stage has one responsibility and does not call adjacent stages directly. `PipelineRunner` owns stage order; `JobRunner` owns the end-to-end run.

---

## Setup

**Requirements:** Python 3.12+, `[uv](https://github.com/astral-sh/uv)`

```bash
uv sync
```

Copy the environment template and fill in the keys you need:

```bash
cp .env.example .env
```

---

## Configuration

| Variable                        | Required for                         | Where to get it                                                               |
| ------------------------------- | ------------------------------------ | ----------------------------------------------------------------------------- |
| `GOOGLE_PLACES_API_KEY`         | `google` source                      | [Google Cloud Console](https://console.cloud.google.com/) → Maps → Places API |
| `YELP_API_KEY`                  | `yelp` source                        | [Yelp Fusion](https://fusion.yelp.com/) developer portal                      |
| `APIFY_API_KEY`                 | `google-apify`, `yelp-apify` sources | [Apify Console](https://console.apify.com/) → Settings → Integrations         |
| `SUPABASE_URL` / `SUPABASE_KEY` | storage (future)                     | Supabase project settings                                                     |

Optional path overrides (defaults shown):

```env
EXPORT_PATH=exports
RUNS_PATH=runs
CACHE_PATH=.cache
LOG_LEVEL=INFO
HEADLESS=True
```

---

## Running a job

Define a job in YAML. A delivery job starts with client-provided data, an
approved registry, or an approved licensed provider. CMS NPPES is the narrow
official-registry connector currently approved for V1. Directory, Google/Yelp
API, and third-party Apify connectors are intentionally blocked from
client-delivery runs until each underlying source has been reviewed and
approved for delivery rights, export use, retention, rate limits, and cost.

### Command line

The installed command keeps normal use to three explicit operations:

```bash
biz-intel preflight jobs/client_job.yaml
biz-intel run jobs/client_job.yaml
biz-intel resume jobs/client_job.yaml runs/<run-id>.checkpoint.json
```

`preflight` makes no source, Keychain, or provider request. Use `--quiet` with
`run` or `resume` when embedding the command in another process. The runner
still applies source policy, cost, and verification safeguards; a command does
not grant a source additional approval.

```yaml
version: 1
name: dentists-san-jose
search:
  query: dentist
  cities:
    - San Jose, CA
sources:
  - csv # seed records or a previous run to reprocess
processing:
  deduplicate: true
  enrich: true # first-party website enrichment, after deduplication
delivery:
  profile: standard
  include_non_accepted: false # default: incomplete records stay in sidecars
output:
  format: csv
  fields:
    - name
    - phone
    - website
    - linkedin
    - instagram
source_options:
  csv:
    path: data/raw/client_businesses.csv
```

Run it:

```python
from biz_intel.jobs import load_job
from biz_intel.jobs.runner import JobRunner
import main  # registers all sources

main.register_sources()
job = load_job("jobs/dentists_san_jose.yaml")
result = JobRunner().run(job)
print(result)
```

Results land in `exports/` and a sanitized run manifest in `runs/`.
Each run keeps its main export and delivery sidecars together at
`exports/<job-name>/<run-id>/`; manifests, checkpoints, and history remain in
`runs/`.
During a run, the console prints one data-free milestone per stage (acquire,
validate, normalize, deduplicate, enrich, classify, export). Pass
`progress_reporter=None` to `JobRunner` when embedding it in a quiet process.

### Run controls and continuity

Call `JobRunner().preflight(job)` before a large run to inspect planned task and
record ceilings, maximum source invocations, known capped enrichment spend, and
any enrichment source whose configured cost remains unbounded. It is planning
only: it neither invokes a source nor approves one for delivery.

Runs write sanitized checkpoints after each source task, omitting raw provider
payloads. To continue an interrupted run with the exact same job definition:

```python
result = JobRunner().run(job, resume_from="runs/<run-id>.checkpoint.json")
```

Completed runs also store a local, sanitized accepted-record snapshot. Stable
record IDs and the manifest's history section show records that are new,
updated, unchanged, or missing versus that job's prior completed run.

### Standard delivery contract

The default `standard` profile writes only **accepted** records to the main
CSV/JSON. An accepted record has a business name, meaningful location, phone
or website, an evidence URL, and an observation time. It does not infer a
missing value or regard a contact as outreach-ready.

Every run writes a compact `*.summary.json` next to the main export. It reports
acquired/classified/delivered counts, duplicate removals, field completeness,
non-accepted reasons, and safe pipeline metrics. It contains no raw provider
payloads. Runs may also write two record-level JSON sidecars:

- `*.quality.json` keeps every record's `accepted`, `incomplete`, `closed`,
  `out_of_scope`, `duplicate`, or `needs_review` status, reasons, and current
  email/phone quality state.
- `*.evidence.json` records field-level source, evidence URL, observation
  time, and collection method—without raw provider payloads.

Set `delivery.include_non_accepted: true` only for a review import where the
recipient explicitly needs the incomplete records in the main export.

Set `delivery.max_age_days` when the client requires current observations;
records older than that threshold remain in the evidence sidecar but are
classified `incomplete` rather than delivered as accepted.

### Optional phone validation

Twilio Lookup Basic is an explicit, post-dedup phone check. It is disabled
unless a job selects it, cannot run in `live_smoke`, and retains no raw Twilio
response. Its `provider_valid` / `provider_invalid` result is a number-validity
signal—not proof of ownership, outreach consent, or business identity.

Keep the restricted Twilio API key and secret in separate macOS Keychain
generic-password items. The YAML contains only their service names, never a
credential:

```yaml
verification:
  phone:
    provider: twilio_lookup_basic
    api_key_service: biz-intel-twilio-api-key
    api_secret_service: biz-intel-twilio-api-secret
```

The Keychain items must be accessible to the user running the job. Use a
restricted key scoped to Lookup; do not use an account Auth Token or a broad
standard key. Email verification remains unconfigured until a client approves
an email provider's cost and data-retention terms.

---

## Source policy

| Source class | Default for a client delivery | Purpose |
| --- | --- | --- |
| `client_input` | allowed | Seed records or prior-run data supplied for processing under the engagement agreement. |
| `official_registry` | review required per registry | Authoritative identity/location data with its own terms. |
| `licensed` | review required per provider and job | Data whose delivery/reuse rights and budget are confirmed. |
| `first_party_web` | enrichment only | Public business contact/team/social pages, within site policy and crawl limits. |
| `experimental_or_disallowed` | blocked | Parser research and offline fixtures only; never a client export. |

Google, Yelp, Yellow Pages, and third-party Apify actor integrations currently
belong to the last class. Running an actor through Apify does not change the
underlying site's delivery rights. They remain useful as sanitized parser
fixtures while policy review is pending.

Runtime caches follow the registered source policy rather than one global
retention period. Experimental/disallowed sources retain no contact-detail
cache entries; an approved source must declare its own retention window.

`nppes` supplies provider identity, practice location, and practice phone. It
does not establish licensing status, email, website, social profile, or
outreach consent. A delivery still needs its scoped job, evidence/freshness
review, and any client-specific attribution check.

## Source integrations

| Source name    | Kind              | Cost per 1 000 records                    | Notes                                                       |
| -------------- | ----------------- | ----------------------------------------- | ----------------------------------------------------------- |
| `yellowpages`  | Scrapy/Playwright | varies | experimental; blocked from client delivery |
| `google`       | API               | varies | experimental; blocked from client delivery |
| `yelp`         | API               | varies | experimental; blocked from client delivery |
| `google-apify` | Apify             | varies | experimental; blocked from client delivery |
| `yelp-apify`   | Apify             | varies | experimental; blocked from client delivery |
| `nppes`        | CMS NPPES API     | zero spend | approved official-registry V1 path |

All sources produce the same `Business` record — the pipeline and enrichment layers are source-agnostic. A policy decision, not the technical adapter, determines whether a source can be used for delivery.

---

## Enrichment

Enrichment runs **after deduplication** so each unique business is enriched at most once.

### Provider contact enrichment (`enrich_details: true` in `source_options`)

Calls Google Place Details or Yelp Business Details for phone and website. This
is disabled by default, subject to the provider's terms, and is not part of an
approved delivery path yet. Retention is source-specific: experimental and
unapproved sources use zero-day retention, while an approved source must
declare its own cache window before its contact details can be retained.

Inspect or export the cache at any time:

```python
import duckdb
conn = duckdb.connect(".cache/place_details.db")
conn.execute("SELECT source, COUNT(*) n FROM place_details_cache GROUP BY source").df()
conn.execute("COPY place_details_cache TO 'cache.parquet' (FORMAT PARQUET)")
```

### First-party website enrichment (`processing.enrich: true`)

Crawls a business's own public website after deduplication, subject to its
robots policy and bounded same-site page limits. It can extract openly listed
general email, phone, and LinkedIn/Instagram/Facebook/Twitter/X links, without
guessing people or contact details. It has no provider charge; a job still
needs permission to use the relevant website data. Each enriched value carries
first-party page evidence and stays `not_checked` until an explicitly requested
verification provider is added later.

### Capping enrichment cost (`max_enrich`)

`source_options.{source}.max_enrich: N` caps the number of **paid**
contact-details calls per source per run (for example Google Place Details or
Yelp Business Details). Every paid source needs a finite cap; an omitted cap
permits zero paid calls. A positive cap also requires a positive
`budget.max_total_usd` and a non-sensitive `budget.approval_reference`. The
runner rejects a configured estimate above that total.

- **Cache hits are free** — a known `place_id` is never re-fetched within its
  source-approved cache window, and never counts against the cap.
- **Capped businesses stay in the dataset** — the cap stops spending, not data; the business's source record is kept with contact fields left empty.
- **Reported in the run manifest** — every run that sets `max_enrich` records a `cost` section: per-source `paid_calls`, a `capped` flag, and an estimated spend (`services/enrichment/budget.py` holds the per-call estimate). Spend is an upper bound until free-tier accounting lands.

```yaml
source_options:
  google:
    enrich_details: true
    max_enrich: 50      # at most 50 paid Place Details calls this run
budget:
  max_total_usd: 1.00
  approval_reference: client-order-42
```

## Offline fixtures and source health

Normal parser work uses versioned fixtures under `tests/fixtures/`. Provider
fixtures are declared in `tests/fixtures/manifest.json`; the validator checks
their content hash and requires synthetic, sanitized fixture claims. CSV
examples also use only reserved `.example.test` contact values. Real client
input belongs in the ignored `data/raw/` landing area. This keeps tests
repeatable without provider calls or committed client data.

`SourceHealthTracker` records per-source success, empty, retryable, fatal, and
skipped outcomes. Job runs record manifest-safe, generic failure codes rather
than raw exception text, and live-smoke runs use its failure threshold to stop
later tasks for an unhealthy source.

## Controlled live-smoke mode

Normal jobs use `execution.mode: delivery`; this is the default and does not
make a provider live. A live smoke job must explicitly set
`execution.mode: live_smoke`, and every selected source must separately be
approved for both delivery and live smoke and declare a `zero-spend` cost
model. No current provider adapter has that approval, so this mode is covered
only by offline test doubles today.

Live smoke is acquisition-only and zero-spend: it rejects website and provider
enrichment, requires `max_cost_usd: 0`, permits at most 3 tasks, 25 records per
task, and 3 attempts per task. Retries use bounded backoff and source-health
thresholds. The record limits below are enforced before records enter the
pipeline; `total_records` is therefore both an acquisition ceiling and a final
delivery ceiling. The maximum source invocations are `max_tasks × max_attempts`
(at most 9); `max_attempts` includes the first call.

```yaml
execution:
  mode: live_smoke
  live_smoke:
    max_tasks: 1
    max_records_per_task: 10
    max_attempts: 2       # includes the first attempt; hard maximum is 3
    retry_backoff_seconds: 1
    failure_threshold: 2
    max_cost_usd: 0
limits:
  total_records: 10
  per_source_records: 10
  per_location_records: 10
```

The legacy top-level `limit` remains a compatibility alias for
`limits.total_records`; a job may not specify both. Task results audit capped
or withheld work as `skipped` without exposing provider exception payloads.

---

## Testing

```bash
uv run python -m unittest discover -s tests -v
```

Run a single file:

```bash
uv run python -m unittest tests/test_enrichment.py -v
```

---

## Project layout

```text
biz_intel/
├── core/               execution primitives (SourceTask, SourceRegistry, executors, BaseApiSource, BaseApifySource)
├── jobs/               job spec (JobSpec, Planner, JobRunner, RunResult)
├── storage/            stable record IDs and sanitized local run history
├── models/             Business domain model
├── pipelines/          validation, normalization, deduplication stages
├── services/
│   ├── enrichment/     ContactEnricher, SocialEnricher, PlaceDetailsCache, EnrichmentBudget, EnrichmentRunner
│   ├── verification/   optional Keychain-backed Twilio Lookup Basic validation
│   └── exporter.py     CSV / JSON export with field projection
└── sources/
    ├── google/         GooglePlacesSource (API) + GoogleMapsApifySource (Apify)
    ├── yelp/           YelpSource (API) + YelpApifySource (Apify)
    ├── yellowpages/    YellowPagesSpider (Scrapy + Playwright)
    └── csv/            CSVSource (debug / import path only)

jobs/                   YAML job definitions
tests/fixtures/         committed synthetic CSV and provider-parser fixtures
data/raw/               ignored client-supplied input landing area
exports/                job output files
runs/                   manifests, checkpoints, and ignored local history (JSON)
.cache/                 DuckDB place details cache
```

---

The public repository contains the project overview, safe demo fixtures, and
test suite. Operational notes and client-run artifacts are intentionally kept
outside this showcase repository.
