# Biz Intel

Biz Intel is a reusable workspace for researching businesses. Start with a
bounded search or an existing list, keep the results as a session, and apply
small evidence plugins without restarting the search.

> **Status:** Active work in progress. The research-session workflow below is
> usable today; plugins and source coverage are still expanding.

Development began in July 2026. The current public history was consolidated
from a private working branch so local notes and research records would not be
published. See the [development timeline](docs/HISTORY.md).

```text
Search or import
      ↓
Saved research session
      ↓
Refine with one or more plugins
      ↓
Review evidence and unknowns
      ↓
Export CSV or JSON
```

The bounded acquisition and export pipeline remains the foundation beneath
the newer session-and-plugin workflow:

![Biz Intel acquisition and export pipeline](assets/portfolio/pipeline.svg)

It is deliberately smaller than a general scraping platform. Sources find
candidates; plugins answer narrow questions about those candidates; sessions
keep the work together so it can be inspected, continued, and exported.

## What it can do

- Search approved registries and import CSV or JSON lists.
- Normalize and deduplicate business records.
- Continue research without repeating the original search.
- Check official-program participation by exact identifier.
- Gather evidence from reviewed first-party websites.
- Find public email addresses and business-linked social profiles.
- Preserve provenance, unknowns, and inaccessible-site outcomes.
- Export a clean table while retaining the richer research record.

## Core concepts

**Job.** A YAML file describing an initial search or import, its limits, and
its output.

**Session.** The saved research workspace containing businesses, evidence,
claims, refinements, and audit outcomes.

**Plugin.** A focused capability applied to businesses already in a session.
A plugin may add evidence or contact fields, but it does not restart the
original search.

**Source policy.** The rules governing how a source may be accessed, retained,
and exported. Technical access alone does not make a source export-eligible.

## Quick start

Requirements: Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync
cp .env.example .env
```

Check a job without contacting its sources, then start a research session:

```bash
biz-intel preflight jobs/oct_dentists_san_jose_metro.yaml

biz-intel research jobs/oct_dentists_san_jose_metro.yaml \
  "Dentists in San Jose"
```

Apply one or several supported plugins to the same records:

```bash
biz-intel refine --latest \
  "Which accept Medi-Cal and have been open 10+ years?"
```

Inspect the result without changing it, then export when ready:

```bash
biz-intel view --latest=1 -10
biz-intel view --summary
biz-intel view --audit
biz-intel research-export --latest exports/dentists.csv
```

`view` defaults to a JSON preview. It can select fields, filter for populated
contacts, show all records instead of only the latest matches, and inspect an
older session. See [Sessions](docs/SESSIONS.md) for the full working pattern.

## Plugins

Several plugins can complement one another in a single instruction. Each one
keeps its own evidence and audit result.

| Capability | Example request | Result |
| --- | --- | --- |
| Medi-Cal Dental | `Which accept Medi-Cal?` | Exact official enrollment claim |
| Ownership | `Which look independent?` | Explicit first-party ownership evidence |
| Longevity | `Which have been open 10+ years?` | Explicit operating-history evidence |
| Operational status | `Which are closed or retired?` | Explicit closure evidence |
| Public email | `Find their public emails` | Published email and evidence page |
| Social profiles | `Find LinkedIn and other socials` | Business-linked public profiles |

Plugins leave unsupported conclusions unknown. For example, official
Medi-Cal enrollment does not prove that a dentist is accepting new patients,
and a provider's experience does not prove the age of a practice.

See [Plugins](docs/PLUGINS.md) for behavior, boundaries, and audit outcomes.

## Sources and reviewed composition

Sources acquire the initial candidates. Supplemental CSV or JSON files can
then attach reviewed websites or other evidence to matching businesses. Supply
the reviewed file you prepared:

```bash
biz-intel compose --latest path/to/reviewed-websites.csv \
  --source reviewed_websites
```

Composition does not blindly merge similar names. Strong identifiers can
match automatically; conflicts and weaker name/address candidates remain
reviewable. Existing values are not overwritten.

Overture is available as a local, frozen candidate snapshot. It remains a
review aid and is not automatically approved for export. See
[Source policies](docs/SOURCE-POLICIES.md).

## Jobs and output

A job controls candidate acquisition, processing, limits, and the ordinary
flat-file output. Research questions such as ownership or program enrollment
belong to session plugins rather than the initial search YAML.

```yaml
version: 1
name: my-business-research
search:
  query: local businesses
sources:
  - csv
processing:
  deduplicate: true
  enrich: false
delivery:
  profile: standard
  include_sidecars: true
output:
  format: csv
  fields:
    - name
    - address
    - phone
    - website
source_options:
  csv:
    path: data/raw/businesses.csv
```

Ordinary runs write the requested CSV or JSON plus optional quality, evidence,
summary, and composition sidecars. Run manifests, checkpoints, and accepted
record history live under `runs/`. Research sessions live under
`runs/research/` and can be exported independently.

See [Jobs](docs/JOBS.md) for the YAML structure and execution controls.

## Documentation

- [Plugins](docs/PLUGINS.md)
- [Jobs](docs/JOBS.md)
- [Sessions](docs/SESSIONS.md)
- [Source policies](docs/SOURCE-POLICIES.md)
- [Development timeline](docs/HISTORY.md)
- [Dentists in San Jose cookbook](docs/cookbook/dentists-san-jose.md)
- [Commercial cleaning cookbook](docs/cookbook/commercial-cleaning.md)

## Safeguards

- Default operation is zero spend. Paid capabilities require explicit finite
  limits and approval metadata.
- Website plugins respect robots policy and report TLS, DNS, timeout, HTTP,
  redirect, connection, and URL failures instead of bypassing them.
- Public email discovery does not imply deliverability or permission to
  contact someone.
- Tests use sanitized fixtures; live provider calls are not ordinary tests.
- Missing or unsupported information stays blank or unknown.

## Development

```bash
uv run python -m unittest discover -s tests -v
```

Git history contains the detailed public implementation record.
