# Research sessions

A session is the durable research workspace. It keeps candidate records,
provenance, claims, plugin history, composition decisions, and crawl outcomes
together so the work can continue without repeating the original search.

## Start or import

Start with an existing job:

```bash
biz-intel research jobs/oct_dentists_san_jose_metro.yaml \
  "Dentists in San Jose"
```

Or continue from an earlier CSV or JSON result:

```bash
biz-intel research-import exports/dentists.csv \
  "Dentists in San Jose" \
  --session runs/research/dentists.json
```

Known NPPES registry URLs are restored as exact NPI identifiers during import,
allowing official-identifier plugins to continue working.

## Select a session

```bash
biz-intel sessions
biz-intel view --latest=1 -10
biz-intel view --latest 3 -10
```

`--latest 3` means the third-newest session. Explicit session names or JSON
paths can be used when recency would be ambiguous.

## Inspect without changing

```bash
biz-intel view -10
biz-intel view --summary
biz-intel view --audit
biz-intel view --audit 2
biz-intel view --all -10 --fields name,phone,website
biz-intel view --with instagram --fields name,phone,instagram -10
```

The normal view defaults to 20 JSON records satisfying every plugin selected
by the latest instruction. `--all` ignores that latest-match filter without
changing the session. `--summary` reports field and claim coverage. `--audit`
groups plugin and crawler outcomes; a number selects an older plugin step.

## Attach reviewed data

Supply a reviewed CSV or JSON file prepared for the businesses in the session:

```bash
biz-intel compose --latest path/to/reviewed-websites.csv \
  --source reviewed_websites
```

Several CSV or JSON files may be listed in one operation. Composition uses
identifiers and conservative identity checks, never overwrites populated
values, and retains matched, candidate, and ambiguous decisions for review.

## Refine

```bash
biz-intel refine --latest "Which dentists accept Medi-Cal?"

biz-intel refine --latest \
  "Which look independent and have been open 10+ years?"

biz-intel refine --latest \
  "Find public emails, LinkedIn, and other socials"
```

Every refinement updates the same session. See [Plugins](PLUGINS.md) for the
evidence rules and limitations.

## Export

```bash
biz-intel research-export --latest exports/dentists.csv
biz-intel research-export --latest --matches exports/dentists-matches.csv
```

The first command exports the complete session. `--matches` exports only
records satisfying every criterion triggered by the latest instruction. CSV
and JSON exports include core business fields, supported claims, discovery
sources, and combined evidence links. Unknown values remain explicit.

Session files live under `runs/research/`. Ordinary run manifests and
checkpoints live directly under `runs/`, while accepted-record history lives
under `runs/history/`.
