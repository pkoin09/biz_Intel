# Commercial cleaning list

This recipe demonstrates the same pipeline with a controlled CSV input instead
of a live registry search.

The example job is `jobs/commercial_cleaning.yaml`. Its fixture intentionally
contains messy synthetic records so normalization, deduplication, quality
classification, sidecars, and optional phone verification can be exercised
without treating the fixture as real business research.

## Check the job

```bash
biz-intel preflight jobs/commercial_cleaning.yaml
```

Preflight reads the job plan without calling a source or verification
provider. Review the configured phone provider and credentials before a real
run.

## Run the controlled example

```bash
biz-intel run jobs/commercial_cleaning.yaml
```

The output includes the requested CSV projection and, when enabled, quality,
evidence, and summary sidecars. The sidecars make rejected, incomplete, and
duplicate records inspectable instead of silently dropping the reason.

## Adapt the recipe

For a real list, copy the job and change:

- `name`
- `search.query` and geography labels
- `source_options.csv.path`
- record limits
- output fields
- verification settings, if verification is actually required

Keep credentials outside the job file. If the next task involves progressive
questions rather than a one-time cleanup, start a research session from the
adapted job and apply plugins to that session.
