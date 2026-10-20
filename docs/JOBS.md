# Jobs

A job YAML describes initial candidate acquisition and the ordinary run
output. It is not the place for every later research question. Questions such
as ownership, longevity, program participation, email, and social profiles are
applied to a saved session through plugins.

## Structure

```yaml
version: 1
name: example-job

search:
  query: Dentist
  cities:
    - San Jose, CA

sources:
  - nppes

processing:
  deduplicate: true
  fuzzy_deduplicate: false
  enrich: false

execution:
  mode: delivery
  max_parallel_tasks: 1

delivery:
  profile: standard
  include_non_accepted: false
  include_sidecars: true

limits:
  total_records: 100
  per_source_records: 100
  per_location_records: 100

output:
  format: csv
  fields:
    - name
    - category
    - address
    - city
    - state
    - postal_code
    - phone
    - source_url
```

## Sections

| Section | Purpose |
| --- | --- |
| `search` | Business category and geographic scope sent to source tasks. |
| `sources` | Acquisition plugins used for the initial candidate set. |
| `processing` | Normalization, exact or fuzzy deduplication, and optional first-party enrichment. |
| `execution` | Run mode and task concurrency. |
| `delivery` | Acceptance profile and sidecar behavior for an ordinary run. |
| `limits` | Aggregate record ceilings across the run. |
| `output` | Flat-file format, projection, and optional destination. |
| `source_options` | Source-specific paths and bounded provider settings. |
| `verification` | Optional approved verification provider configuration. |
| `budget` | Explicit ceiling and authorization metadata for paid capabilities. |

`processing.enrich: true` crawls first-party websites already present on the
records after deduplication. It does not discover missing websites. For an
NPPES-only job, reviewed websites normally need to be composed into the
research session first.

Limits are aggregate. For example, five cities with `total_records: 100` still
produce at most 100 records overall; the limit is not multiplied by five.

If `output.destination` is omitted, the tool creates a run-specific export
location. A fixed destination is useful for a deliberate stable target, but a
later run may replace that file.

## Check and run

`preflight` performs no source, credential-store, or provider request. It
reports planned tasks, record ceilings, and known cost bounds.

```bash
biz-intel preflight jobs/example.yaml
biz-intel run jobs/example.yaml
```

Start a persistent research session instead when later refinements are
expected:

```bash
biz-intel research jobs/example.yaml "Plain-language research goal"
```

Resume an interrupted ordinary run from its sanitized checkpoint:

```bash
biz-intel resume jobs/example.yaml runs/<run-id>.checkpoint.json
```

## Credentials and spend

Credentials belong in macOS Keychain under the `biz-intel` service or in the
ignored `.env` development fallback. They do not belong in YAML, fixtures,
manifests, or Git.

Paid acquisition, enrichment, or verification must use an approved source,
finite provider limits, `budget.max_total_usd`, and an approval reference.
The default path is zero spend.
