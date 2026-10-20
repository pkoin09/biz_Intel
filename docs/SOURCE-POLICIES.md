# Source policies

Every acquisition source declares a policy in code. The policy separates
technical availability from approved use: being able to query, scrape, or
download a source does not automatically make its records eligible for export.

## Current source roles

| Source | Export status | Intended role |
| --- | --- | --- |
| `csv` | Allowed | User-controlled input, seed lists, and prior exports |
| `nppes` | Approved V1 path | Provider identity, practice location, phone, and NPI |
| `wa-li` | Registry research | Washington contractor-registration evidence |
| `ca-dental-board` | Manual evidence import | Reviewed California dental-license evidence |
| `overture` | Blocked | Local candidate discovery and matching review |
| `google`, `yelp`, `yellowpages` | Blocked | Experimental connectors pending source-specific review |
| `*-apify`, including `linkedin-apify` | Blocked | Actor-backed observations pending source-specific review |

Policies may also declare retention, attribution, rate, fixture, live-smoke,
and cost constraints. Export status is enforced before an ordinary run issues
source requests.

## Overture boundary

Overture is consumed from a local GeoParquet snapshot with a companion
manifest. The manifest pins release, retrieval time, scope, attribution,
license observation, row count, and content hash. Preparing a snapshot does
not download data, select an implicit latest release, overwrite an existing
snapshot, or grant export approval.

Prepared records are candidates. `overture-review` compares a snapshot you
provide with a saved session and reports matched, candidate, and ambiguous
links without changing the session:

```bash
biz-intel overture-review --latest \
  path/to/overture-snapshot.parquet \
  --decision candidate --offset 20 -n 10
```

Any first-party website chosen from those candidates still requires identity
review before it is composed into the research session.

## Spend and credentials

Default operation is zero spend. A spending cap limits cost but does not grant
source rights. Paid acquisition or verification must have both an approved-use
policy and explicit finite job limits.

Credentials are retrieved from the credential store or ignored local
environment configuration. They are never written to exports, evidence
sidecars, manifests, or committed fixtures.
