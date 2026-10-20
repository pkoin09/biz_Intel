# Dentists in the San Jose area

This recipe starts with official NPPES provider candidates and progressively
adds evidence without rerunning the original search.

## 1. Review the search job

The job searches five cities and caps the combined result at 100 records:

```bash
biz-intel preflight jobs/oct_dentists_san_jose_metro.yaml
```

NPPES supplies provider identity, practice location, phone, taxonomy, and NPI.
It does not establish Medi-Cal participation, ownership, business age, email,
social identity, or whether a practice is accepting new patients.

## 2. Start the session

```bash
biz-intel research jobs/oct_dentists_san_jose_metro.yaml \
  "Dentists in San Jose"
```

The printed JSON path is the durable session record. Later commands may use
that path explicitly or select it with `--latest`.

## 3. Check official Medi-Cal Dental enrollment

```bash
biz-intel refine --latest "Which dentists accept Medi-Cal?"
```

The plugin checks exact NPIs against the public California DHCS Medi-Cal
Dental FFS directory. A positive result establishes enrollment, not current
availability or acceptance of new patients.

## 4. Attach reviewed first-party websites

NPPES normally does not provide websites. Review candidate sites separately,
record identity evidence, and compose the accepted records from your prepared
CSV or JSON file:

```bash
biz-intel compose --latest path/to/reviewed-websites.csv \
  --source reviewed_websites
```

Overture can help locate candidates from a local snapshot you prepared, but its
matches remain review-only:

```bash
biz-intel overture-review --latest \
  path/to/overture-snapshot.parquet \
  --decision candidate -n 10
```

## 5. Gather first-party evidence

Run related website plugins together so they can reuse one bounded crawl:

```bash
biz-intel refine --latest \
  "Which look family-owned or independent, have been open 10+ years, and which are closed?"

biz-intel refine --latest \
  "Find public emails, LinkedIn, and other socials"
```

The plugins require explicit evidence. A dentist's years of experience does
not establish practice age, and the absence of corporate language does not
establish independent ownership.

## 6. Inspect the research

```bash
biz-intel view --summary
biz-intel view --audit
biz-intel view --all -10 --fields name,phone,website,email
```

If a combined refinement has no latest matches, inspect each plugin's coverage
before assuming the search failed. Combined instructions use AND semantics;
the full candidate set remains in the session.

## 7. Export

```bash
biz-intel research-export --latest exports/dentists.csv
biz-intel research-export --latest --matches exports/dentists-matches.csv
```

Use the full export for the research table. Use `--matches` only when the
latest combined criteria describe the exact subset wanted.
