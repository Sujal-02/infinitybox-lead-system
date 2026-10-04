# InfinityBox lead system: architecture (one page)

**What it does.** Finds organisations in a chosen city that are likely to need offsite/onsite warewashing or kitchen design *now*, finds the right person to write to, scores each lead with a visible reason, writes an editable draft per company, and routes inbound enquiries from a public calculator page to the right team. **Nothing is ever sent by this system.** The Send button is a placeholder that records to an outbox.

```
 config/*.yaml (cities, sources, triggers, weights, roles, hierarchy, playbook, budgets)
        |
 1 DISCOVER ── news RSS + city/national source list + Firecrawl search ──► docs (url, date, text)
 2 EXTRACT  ── keyword prefilter, then Gemini Flash reads headlines in batches ──► signals
               guard: every signal must carry a quote that is a verbatim substring of the page
 3 SCORE    ── fixed rules, no LLM: Fit 40 + Trigger 45 (decays with age) + Reach 15 = 100
 4 PEOPLE   ── org website first (Firecrawl) → optional Apify LinkedIn actor → Hunter only if
               no relevant name yet; hierarchy ranks tier 1/2/3 and flags gatekeepers
               emails come ONLY from Hunter or the page itself, never generated
 5 DRAFT    ── Gemini writes the message body per company from the playbook; code adds greeting
               and sign-off; guardrails reject forbidden words, unsupported numbers, invented emails
        |
 Lead desk (local web app, app/)  ──►  outbox.json / workbook .xlsx / Google Sheet (optional)

 Public page (inbound/, static)  ── calculator → form ──► Google Apps Script web app
        ├─ appends row to Sheet tab "Leads", routes by segment, emails the team
        └─ anonymous funnel events → Sheet tab "Events" (also shown in the Lead desk)
```

## Where each part lives
| Part | Files | Notes |
|---|---|---|
| Pipeline | `src/` (`run.py` is the CLI) | each step reads/writes JSON in `data_<city>/`; everything cached in `cache/` |
| Config | `config/` | change cities, triggers, weights, roles, claims here, not in code |
| Lead desk (non-technical UI) | `app/` | Home, Leads, Find leads, Website enquiries, Outbox. `start.bat` / `start.sh` |
| Public page | `inbound/` | static HTML + `calc.js` (savings estimate) + `apps_script.gs` (backend) |
| Autonomous variant | `brain/` | Gemini-only agent that uses the same tools; score still computed by code |

## Scoring (visible on every lead)
Fit ≤40 (segment, city, size, cafeteria on site) · Trigger ≤45 (type weight, halves every N days; best signal per type) · Reach ≤15 (named relevant person, valid email, known caterer). Each point has a label on screen, plus "to raise this score" tips. Weights are in `config/weights.yaml`.

## Inbound, trackers and the sheet
- Calculator → form → Apps Script → **Leads** tab, routed: corporate/institution → warewashing, fit-out → kitchen design, caterer → partnerships. A honeypot field drops bots.
- **Trackers:** first-party, anonymous funnel events only (visited, started, chose items, saw result, opened form, sent). No cookies, no third-party scripts, no IP or name stored, "Do Not Track" respected. They answer "which outreach batch brought people, and where do they drop?" through `?utm_campaign=` on links in emails.
- Only genuine enquiries (valid email + company + segment) reach the Leads tab; events go to a separate tab so the lead list stays clean.

## Monthly cost (₹, FX assumed ₹90 per US$; vendor prices change, verify before buying)
| Item | Free tier used in this build | If scaled up | ₹ / month |
|---|---|---|---|
| Gemini Flash (extraction, drafts) | free tier | about US$0.25 in / 1.50 out per 1M tokens; a 25-lead city run is well under ₹50 | ~150 |
| Firecrawl (search + page reads) | 1,000 free credits | Hobby plan US$19 | 1,710 |
| Hunter (verified emails) | 50 free searches | Starter US$49 | 4,410 |
| Apify (optional LinkedIn actors) | free credit | Starter US$19 | 1,710 |
| GitHub Pages, Apps Script, Google Sheet, local app | free | free | 0 |
| **Total** | **₹0** | | **≈ ₹8,000** |

Budget guard (`config/budgets.yaml`): per-run and monthly caps per service; the desk shows live balances and stops before a limit is hit.

## Staying out of trouble (platform terms, bans)
- **No LinkedIn login, no cookies, no automation of any account.** The desk only builds LinkedIn *search links* that a person opens. The optional Apify actors read public pages without a session; that sits in a grey area of LinkedIn's terms, so it only runs if `APIFY_TOKEN` is set in `.env` (leave it empty to switch it off), and the rest of the system works without it.
- Public data only: news, company sites, public registries. robots.txt is respected by Firecrawl; requests are cached and capped, so nothing is hit twice.
- **No email is sent from this system**, so there is no risk to a sending domain from it. When real sending is added: a separate subdomain, SPF/DKIM/DMARC, warm-up, ≤30/day per mailbox, unsubscribe line, one human-approved message at a time.
- DPDP: business-role data only (name, role, work email from a public source or Hunter); source link kept next to each person; nothing personal beyond that.

## Assumptions and limits
- Savings figures on the public page are estimates from stated averages (labelled "InfinityBox reports"), not guarantees; the form says so.
- Claims in drafts come only from `config/playbook.yaml`; add proven numbers and client names there, nothing else is allowed.
- Hunter's free tier is small, so it is used last; coverage of named people is the main limit on the Reach score.
- Where we went deep: **targeting** (trigger evidence with quotes, contact hierarchy that separates buyers from gatekeepers) and **engagement** (per-company drafts with guardrails).

## Deploy (two options)
1. **Local (works today):** `start.bat` (Windows) or `./start.sh`, fill `.env`, open http://127.0.0.1:8765.
2. **GitHub:** push the repo (`.env`, `creds.json`, `data*/` are git-ignored); publish `inbound/` with GitHub Pages; deploy `inbound/apps_script.gs` as a web app and paste its URL into the page; a scheduled GitHub Action can run `python -m src.run all --city <City>` weekly.
