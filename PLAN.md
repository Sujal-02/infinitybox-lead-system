# InfinityBox Lead System: Plan

Find companies likely to buy InfinityBox services (offsite/onsite warewashing, kitchen design) right now, pick the role to approach, score with a visible reason, draft outreach, and route inbound calculator leads to the team. One city per run; output is 25 ranked accounts + 5 drafts.

## Hard rules
- Public data only. Drafts only; no send code anywhere.
- No LinkedIn login. Only cookie-free Apify actors listed in `config/actors.yaml`; any other is refused.
- People search only on the top N scored accounts (default 40).
- Every signal: `source_url` + verbatim `evidence` that is a substring of the fetched text, else reject.
- Business-role data only, with source + purpose per record (DPDP). No personal phones/emails.
- Hunter-verify emails before they reach the sheet.
- Free tiers; every API response cached on disk.

## Build phases
1. Scaffold (configs, models, cache, sheet, `init`) **<- current**
2. Discover + extract
3. Resolve + score
4. People
5. Draft
6. Inbound
7. Docs
8. Actions workflow

## Decisions / notes
- `init` only touches the sheet unless `--dry-run` is passed; `DRY_RUN` env applies to pipeline commands.
- Sheet helpers are generic (`append(book, tab, rows)`) rather than one function per tab; tab columns come from the pydantic models.
- `People` has an extra `purpose` column for the DPDP requirement.
- Brief says "city in the six" but lists four cities; configured four.
