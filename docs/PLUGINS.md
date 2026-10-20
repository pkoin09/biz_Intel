# Plugins

A plugin answers one narrow question about businesses already stored in a
research session. It may add evidence-backed claims or public contact fields,
but it does not repeat the initial search.

One plain-language instruction can select several plugins. They run against
the same records, retain separate audit entries, and reuse a bounded website
crawl when they need the same first-party pages.

## Current plugin catalog

| Plugin | Typical wording | Adds | Boundary |
| --- | --- | --- | --- |
| Medi-Cal Dental enrollment | `Which accept Medi-Cal?` | `program.medi_cal_dental_ffs_enrolled` | Exact NPI matches only; enrollment is not proof of accepting new patients. |
| Ownership evidence | `Which are family-owned or independent?` | `ownership.classification` and evidence | Requires explicit first-party wording; names and location counts are not ownership proof. |
| Longevity evidence | `Which have been open 10+ years?` | Founding year or operating-years claim | NPI dates and provider experience are not practice longevity. |
| Operational status | `Which are closed or retired?` | Explicit closure claim | No closure wording does not prove that a practice is open. |
| Public email | `Find public email addresses` | Email, provenance, and check status | Discovery does not verify deliverability. |
| Public social profiles | `Find LinkedIn and other socials` | LinkedIn, Instagram, Facebook, and X/Twitter | Only profiles linked from reviewed first-party pages are retained. |

## Evidence-first behavior

Plugins add a positive or negative conclusion only when their evidence rule is
satisfied. Otherwise the field remains unknown or unclear. This prevents a
missing phrase, inaccessible website, or suggestive business name from being
silently converted into a fact.

First-party website plugins distinguish a successful crawl with no supporting
evidence from a site that could not be read. Audit outcomes include robots
denial, invalid TLS, DNS failure, timeout, HTTP error, connection failure,
redirect failure, and invalid URL. These restrictions are reported, not
bypassed.

## Running plugins

Apply one plugin:

```bash
biz-intel refine --latest "Which dentists accept Medi-Cal?"
```

Apply several to the same session:

```bash
biz-intel refine --latest \
  "Which accept Medi-Cal, look independent, and have been open 10+ years?"
```

Inspect what ran and how each site was handled:

```bash
biz-intel view --audit
biz-intel view --audit 2
biz-intel view --summary
```

The latest-match view uses AND semantics: when one instruction invokes several
plugins, a record must satisfy every triggered criterion to appear as a latest
match. The full session remains intact and is available with `view --all` or a
normal research export.

## Adding a plugin

A plugin should remain narrow and reusable. It should declare what evidence it
accepts, preserve provenance, record inaccessible or inconclusive outcomes,
and avoid turning absence into a conclusion. Provider-specific setup and long
operational instructions should move into a dedicated page only when the
plugin becomes complex enough to need one.
