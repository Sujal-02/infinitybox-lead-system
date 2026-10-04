# AI Log

Every AI mistake and how it was caught. Append, never rewrite.

| Date | Phase | Mistake | How caught | Fix |
|---|---|---|---|---|
| 2026-10-02 | 1 | `cache.py` created the cache dir without `parents=True` | `test_cache_hits_disk` failed with FileNotFoundError | `mkdir(parents=True, exist_ok=True)` |
| 2026-10-02 | 2 | Test fixture of a fabricated LLM "evidence" is kept on purpose (Northwind 5,000-seat campus) | n/a, a regression guard, not a bug | `test_end_to_end_dry_run` asserts it is rejected |
| 2026-10-03 | 4 | Website contact extractor credited a generic `info@` to a name two blocks above it | `test_website_contacts_only_published_org_addresses` | Context now stops at a blank line |
| 2026-10-03 | 4 | LinkedIn company / website match accepted any slug or host sharing one word (TCS -> `tcspune`, Pune University -> a Sinhgad college, Sassoon -> a yellow-fever site) | Reading the first real Apify/Firecrawl results | Slug/host must match >=60% of distinctive name words with <=1 extra token; `config/overrides.yaml` for manual pins |
| 2026-10-03 | 4 | Role taken from the email line itself (`regis@` scored as Registrar; a finance mailbox scored 0.8) | Reading real extraction output for the university | Lines containing `@` are ignored for role; mailbox name used only as a fallback |
| 2026-10-03 | 4 | Bare `admin` title scored 1.0 as a POC; Hunter `valid`-only rule dropped an `accept_all` address | Real Apify run; user rule change | Loose title matches capped at 0.9; emails stored exactly as Hunter returns, with status |
| 2026-10-03 | 4 | Apify run ended SUCCEEDED with 0 items ("free user run limit exceeded"); code read it as "nobody found" and cached the empty result | Same TCS query returned 5 rows from cache but 0 fresh; read the run log | `check_run` raises on limit/failed status, empty results from failed runs are never cached, 15 poisoned cache files deleted |
| 2026-10-03 | 4 | Re-running contacts for an account overwrote its stored people with an empty result when a source failed | TCS/Bajaj contacts vanished after `contacts --account` | `keep_known`: a rerun with no real contact keeps the old ones; restored from cache |
| 2026-10-03 | 4 | Hierarchy v1 false positives: TCS typed "manufacturing" from "Factory Lab"; `investor.service@` as head of corporate services; "AMS Delivery Manager ... Food Service" as food services manager | Reading real `contacts` output per account | Name-led kind classification; mailbox must match all distinctive title words; order-aware title matching; regression tests |
| 2026-10-03 | 5 | Gemini drafts asserted unsupported facts ("because corporate catering is outsourced", "dining demand will shift") and passed the automatic check | Reading the first real Gemini drafts | Prompt now forbids asserting or predicting beyond the evidence (use "if"/questions); human review of drafts stays |
| 2026-10-03 | 4 | Apify "credits over" was misread as an account problem: the account had $5 left, but the harvestapi actor itself refuses FREE-plan users after 10 runs | Read the run log message ("Free users are limited to 10 runs") and compared with the account plan | Second allowlisted actor (`people_alt`, apimaestro) used automatically when the first is refused; refused actors are skipped for the rest of the run |
| 2026-10-03 | 4 | New Apify adapter filtered people by city but had no alias for Bangalore/Bengaluru, which would silently drop every Bengaluru person | `test_apimaestro_headline_and_city_handling` | `LOCATIONS` aliases for Bangalore, Hyderabad, NCR |
| 2026-10-03 | 4 | LinkedIn headline "Facility Manager at Tata Consultancy Services" scored as excluded because "Consultancy" matches the `consultant` exclusion | Reasoned from the exclude list before running, then tested | Company part of a headline is stripped before role matching |
| 2026-10-03 | 6 | App's Pune list included Vertex Group (NCR) and Airbus (Bangalore) because the data folder mixes cities | Looking at the first screenshot of the app | Datasets carry their own city and filter by it; test added |
| 2026-10-03 | 6 | My patch script read UTF-8 files with the Windows default encoding and crashed halfway, leaving the page half-updated | Traceback, then grep for the expected strings | Re-applied with explicit utf-8; checked every edit actually landed |
| 2026-10-04 | 8 | Dead-code cleanup: my regex that deleted unused `.fields` CSS also ate the start of the next line, leaving an unclosed `@media` block in the public page | Read the diff line by line and counted braces in the stylesheet (234 open, 234 close after the fix) | Restored the line; the diff now shows only deletions. Lesson: review the diff of any automated multi-line edit |
| 2026-10-04 | 8 | `yml()` re-parsed the YAML config on every call (scoring called it per signal), making the test suite take 40 s | Profiling the suite after the cleanup pass | Cached it once per process: suite now about 6 s. Also removed unused imports, a never-used `manual_draft` path, a TODO actor placeholder and stale PLAN.md |

## AI tools used
| Tool | Used for |
|---|---|
| Claude Code (Claude Sonnet 5.5) | Wrote and refactored the code, tests, config and docs in this repo; ran the pipeline and read its output; checked pages in a browser pane |
| Gemini Flash (`gemini-3.8-flash`, fallbacks `gemini-3.7-flash`, `gemini-flash-latest`) | Inside the product: reading headlines into signals, drafting emails per company, and the Gemini-only agent run (`brain/`) |
| Firecrawl, Hunter, Apify (cookie-free actors only) | Data sources inside the product, not coding aids |

## Prompts that shaped the system (in order)
1. The build brief: a config-driven Python pipeline (discover, score, contacts, drafts) with public data only, verbatim evidence for every signal, drafts only, free tiers, everything cached.
2. "Do not hallucinate and generate emails, whatever Hunter or Apollo gives is accepted": emails are never generated; they come only from Hunter or a page that publishes them.
3. "Work on hierarchy of getting contacts and relevance (e.g. the registrar is a gatekeeper)": the contact hierarchy with buyer, day-to-day and gatekeeper tiers.
4. "Create an isolated system where Gemini is only the brain": the `brain/` agent, whose scores and drafts are still computed by code.
5. "For scoring don't rely on the LLM" and "add a template/playbook to reduce hallucination": deterministic scoring and the playbook with approved facts and forbidden words.
6. "A frontend where the draft is written by the LLM from the playbook, editable, with supporting links and scoring shown, for a non-technical user": the Lead desk.
7. The assignment brief (72-hour intern task): the public calculator page, the inbound routing and the deliverables list.
8. "Make the website simple, take inspiration, interactive, radial dials": the public page redesign; later a softer palette and a guided tour.
9. "Wire city_sources into discovery", "clean the codebase", "run a full Pune pipeline": the latest rounds.

## Decisions a person made (not the AI)
- Pune and Bengaluru as the test cities, free-tier-first with budgets, and the rule that nothing is ever sent from this system.
- Never share keys in chat: keys stay in `.env` or repository secrets; the Apps Script is limited to one sheet and no email.
- Which leads to trust: reading the real Pune and Bengaluru output and deciding what was wrong (wrong company site, a registrar listed as buyer, mixed cities, thin evidence).
- Accepting that the Google Cloud key was not allowed on the organisation account and using the Apps Script gateway instead.
| 2026-10-04 | 9 | The app listed a fresh Pune run under the old Pune name but loaded the old data folder (`config()` looked in the built-in list first), so the dashboard snapshot showed 28 stale leads instead of 45 | Counted leads in the exported snapshot after the full run | `config()` now prefers the newer `data_<city>/` list; snapshot re-exported (45) |
| 2026-10-04 | 9 | I applied the "softer, brighter, lighter" palette request to the public page, which the user had only wanted for the leads dashboard; the original public design was the one they liked | The user told me | Public page, sprite, SEO styles and calculator colours restored to the original palette (the tour and dashboard links kept); the lighter palette now lives only in the dashboard. Lesson: confirm which surface a styling request is about when two are in play |
| 2026-10-04 | 10 | Access-code prompt for the hosted dashboard first showed the text "null", opened several dialogs at once (one per parallel request), and a wrong code locked out the right one because every parallel request counted as a guess | Used the dashboard from a second origin in the browser with a wrong code, then the right one | `replaceChildren(null)` filtered; one shared prompt; only requests that carry a wrong code count (limit 20/min); tests added. The Docker image itself is untested here (Docker was not running) |
| 2026-10-04 | 11 | Change of direction: reviewers run the system on their own computers with their own keys instead of a shared hosted dashboard | User decision (keys cannot be shared) | `setup_local.py` (explains each key, validates it, writes `.env`, never prints keys), `start.bat`/`start.sh` call it, local Excel sheet download in the app, README "Run it yourself". The hosted-server route stays in the repo as an option |
| 2026-10-04 | 10 | My commit "Dashboard shows enquiries stored in the sheet" silently reverted two commits (the local-first setup script and its dashboard changes) because my working copy was behind the repository and I committed everything with `git add -A` | Read the commit's file list: it deleted `setup_local.py`, which I had not touched | Reverted my commit (history kept, no force push) and re-applied only my change on top of the current files. Lesson: compare with the remote before committing, and stage named files |
| 2026-10-04 | 10 | Tests passed on my machine but 4 would have failed in CI: they relied on the git-ignored `cache/` folder and local run data, and one asserted `"x" not in` a string that contains "Excel" | Cloned the repository to a clean folder (what the CI runner sees) and ran the suite there | State folder now created with parents; the setup-status test builds its own tiny dataset and uses a distinctive fake key. Lesson: run the tests from a fresh clone before trusting a green local run |
