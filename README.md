# InfinityBox Lead System

Finds companies likely to need cafeteria warewashing or kitchen design **right now**, ranks them with a visible reason, picks the right person to approach, and writes **draft** emails. A public calculator page captures inbound enquiries and routes them to the right team. **Nothing is ever sent by this system**: "Send" only records a draft in an outbox.

## Links and deliverables

| What | Where |
|---|---|
| **Live dashboard** (find leads, write drafts, enquiries, sheet) | https://infinitybox-desk.onrender.com/ (an access code is shared separately; a free host can take a minute to wake up) |
| **Live public page** (calculator and enquiry form) | https://infinitybox-desk.onrender.com/site/ and, on GitHub Pages, https://sujal-02.github.io/infinitybox-lead-system/ |
| Code | this repository (GitHub, private; access shared) |
| Live run on one city: 25 ranked accounts and 5 drafts | [RESULTS_PUNE.md](RESULTS_PUNE.md); the same data is the "Pune" list in the dashboard |
| Architecture, data flow and monthly cost in rupees | [ARCHITECTURE.md](ARCHITECTURE.md) |
| AI log: tools, prompts, decisions, every mistake caught | [AI_LOG.md](AI_LOG.md) |
| Next 30 days | [NEXT_30_DAYS.md](NEXT_30_DAYS.md) |
| Demo video script (under 5 minutes) | [DEMO_SCRIPT.md](DEMO_SCRIPT.md) |

## What is in the box

| Part | What it does | Where |
|---|---|---|
| Lead pipeline | discover, extract signals, score, find contacts, draft; one command or one button per city | `src/` |
| Lead dashboard | non-technical web app: Home, Leads, Find leads, Website enquiries, Outbox | `app/` |
| Public page | calculator with radial dials, enquiry form, anonymous funnel tracking, guided tour | `inbound/` |
| Google Sheet | the database: lead lists keyed by city, plus enquiries and visit events | `src/sheet.py`, `inbound/apps_script.gs` |
| Hosted server | the same app behind an access code with a capped credit allowance | `Dockerfile`, `render.yaml` |
| CI/CD | tests on every push, public page deployed to GitHub Pages | `.github/workflows/` |
| Gemini-only agent | an experiment where Gemini does the research with tools; scoring is still done by code | `brain/` |

## Run it yourself (reviewers: your own free keys, no Google account needed)

1. Install **Python 3.11+** (on Windows tick "Add Python to PATH").
2. Open the project folder. **Windows:** double-click `start.bat`. **Mac/Linux:** `./start.sh`. The first run sets itself up, then `setup_local.py` asks for your keys one at a time, explains what each does and what it costs, and checks that it works before saving. Keys stay in `.env` on your machine (git-ignored).

| Key | What it is for | Without it |
|---|---|---|
| Gemini (aistudio.google.com/app/apikey) | Reads news into signals, writes drafts | Nothing runs (required) |
| Firecrawl (firecrawl.dev, 1,000 free credits) | Web search and page reads: company sites, tenders, trackers | Free news search only: fewer leads, no website contacts |
| Hunter (hunter.io, 50 free searches a month) | Verified work emails, never guessed | Contacts have names and roles, emails only if a site publishes them |
| Apify (about US$5 free a month) | Public LinkedIn company pages, no login | Contacts come from websites and Hunter only |

3. The dashboard opens at http://127.0.0.1:8765. **Find leads**: choose a city, keep "Quick look" (about 4 minutes, a small part of the free credits), press the button and watch the progress.
4. **Leads**: open a company to see why it is a lead, how the score is built, the source links and who to contact. **Write the email** makes an editable draft.
5. No keys at all? `python -m src.run all --city Pune --dry-run` runs the whole pipeline on test data.

Without a Google Sheet, press **Download as Excel sheet** on the Leads tab: the same tabs the sheet would hold.

## How it works

1. **Discover.** Google News queries per city (`config/cities.yaml`); from `config/city_sources.yaml` the city's own queries, and in a wide run one query per tech park, per recently seen expansion, per institution and per local news site; Firecrawl searches; and the fetchable tracker, lease and tender pages.
2. **Extract.** A keyword prefilter, then Gemini reads headlines in batches and returns signals (new campus, lease, cafeteria work, tender, caterer contract, plastic/ESG, facilities hiring). **A signal is kept only if its quote is a verbatim substring of the page it came from**, so an invented event cannot enter the system.
3. **Score** (fixed rules, no LLM): fit up to 40 (segment, city, size, cafeteria on site) + trigger up to 45 (type weight, halves every few weeks) + reach up to 15 (named relevant person, valid email, known caterer). Every point is labelled on screen, with "to raise this score" tips. Weights: `config/weights.yaml`, `config/triggers.yaml`.
4. **Contacts** for the top accounts, in cost order: the organisation's own website, then optional Apify LinkedIn pages, then Hunter. A hierarchy (`config/hierarchy.yaml`) tiers titles per kind of organisation: decision maker, day-to-day owner, gatekeeper (a registrar, used only to ask for an introduction). **Emails are never generated**: only what Hunter returned or a page publishes.
5. **Drafts.** Gemini writes three short paragraphs per company from the playbook (`config/playbook.yaml`, `config/templates.yaml`, 10 styles): why the trigger matters, how InfinityBox works for that kind of organisation, what a first call would cover. It may state only approved facts, must avoid forbidden words, and may quote only numbers found in the evidence; code adds the greeting, a tracked link to the calculator and a `[Your name]` sign-off. The reviewer edits every word, and problems are flagged live.
6. **Send is a placeholder** (`app/mailer.py`): it records the message in the outbox and opens a pre-filled Gmail compose window for a person to send. Nothing is emailed by the app.

## The public page and enquiries

- Calculator: meals per day, items per meal, estimated monthly spend on single-use serviceware with editable placeholder prices. Figures from InfinityBox itself (30% water, 25% electricity, 40% single-use waste) are labelled "InfinityBox reports" and never applied to the visitor's numbers.
- Enquiry form: the visitor says what they are (company, institution, caterer, fit-out); the enquiry is **routed** (corporate and institution to warewashing, fit-out to kitchen design, caterer to partnerships) and stored in the sheet's `Leads` tab. A honeypot field, a minimum fill time and a consent box guard against bots.
- Tracking: first-party, anonymous funnel steps only (visited, started, chose items, saw result, opened form, sent), tagged by outreach batch through `utm_campaign`. No cookies, no third-party scripts, Do Not Track respected. Stored in the `Events` tab.
- Every draft links to the page, pre-filled with the company, segment and city. The dashboard's **Website enquiries** tab shows enquiries and the funnel from the sheet and from the app itself.

## Google Sheet as the database

Lead lists are saved to the sheet, keyed by city (tabs Accounts, Signals, People, Scores, Drafts, Pipeline). Each pipeline run saves its city automatically; the Home tab has **Save to sheet** and **Load from sheet** per city; a server that restarts with an empty disk reloads from the sheet by itself. One city never overwrites another, and a `status` edited in the sheet is kept.

Connect it with either route (both optional; without a sheet, lists stay as local files):
- **Apps Script gateway** (works when a Google Cloud key is not allowed): open the sheet, Extensions, Apps Script; paste `inbound/apps_script.gs`; in Project settings show the manifest and replace it with `inbound/appsscript.json` (one permission: this sheet only, no email); set the script property `API_TOKEN`; Deploy as a web app (execute as you, access Anyone). Put the `/exec` address in `SHEET_WEBHOOK_URL` and the token in `SHEET_API_TOKEN`.
- **Service account key:** enable the Sheets and Drive APIs, create a service account, save its key as `creds.json`, share the sheet with its email, set `GSHEET_ID`.

Then `python -m src.run sheet_check` (plain-words diagnosis) and `python -m src.run init` (creates the tabs).

## Hosting: Render (dashboard) and GitHub Pages (public page)

`render.yaml` and the `Dockerfile` run the same app as a web service. Deploy: render.com, New, Blueprint, pick the repository, fill the keys and choose an `ACCESS_CODE`. In hosted mode:
- every `/api` call needs the access code (wrong codes are rate limited); the public page itself is open;
- credits are capped by `BUDGET_PROFILE=demo` (smaller allowance in `config/budgets.yaml`, Quick look only, one run at a time) and the Home tab shows what is left;
- the public page is served with the sheet address filled in, so enquiries reach the sheet;
- a free host sleeps when idle and loses its disk on restart; lists come back from the sheet.

GitHub Pages serves the static public page and a read-only snapshot of the dashboard (names, emails and LinkedIn profiles removed). Repository variables used by the deploy: `APPS_SCRIPT_URL` (enquiries to the sheet) and `API_URL` (turns the Pages dashboard into a client of the Render server). Pages on a private repository needs a paid GitHub plan.

## Configuration (`.env`)

| Variable | Needed | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes | AI |
| `FIRECRAWL_API_KEY`, `HUNTER_API_KEY`, `APIFY_TOKEN` | optional | web, emails, LinkedIn pages |
| `SHEET_WEBHOOK_URL`, `SHEET_API_TOKEN` | optional | sheet through the Apps Script gateway |
| `GSHEET_ID`, `GOOGLE_CREDS_PATH` | optional | sheet through a service-account key |
| `ACCESS_CODE`, `ALLOWED_ORIGIN`, `BUDGET_PROFILE`, `HOST`, `PORT` | hosted only | access code, allowed website origin, credit cap profile, listen address |
| `APPS_SCRIPT_URL` | optional | overrides the address given to the hosted public page |
| `CITY`, `TOP_N_PEOPLE`, `DRY_RUN`, `GEMINI_MODELS`, `DATA_DIR` | optional | defaults for runs |

`config/budgets.yaml` caps what a run and a month may spend per service; only real (uncached) calls are charged, and a cap stops that source with a message while the run continues. `python -m src.run quota` shows live balances.

## Commands

```
python -m src.run all --city Pune            # everything (add --wide for the full set of queries, --top N)
python -m src.run discover | extract | score | people | draft
python -m src.run leads --city Pune --min-score 30 --has-email --format md
python -m src.run sheet_check | init | quota | check_sources | check_city_sources
python -m app                                # the dashboard (python -m app.export_static rebuilds the Pages snapshot)
python -m pytest -q                          # 94 tests, no keys needed
```

## CI/CD

- `ci.yml`: every push and pull request runs the tests, checks that the built pages match their sources and, in a public repository, that no key file or key-shaped string is tracked.
- `pages.yml`: a push that touches the page or dashboard runs the page tests, injects `APPS_SCRIPT_URL` and `API_URL`, and publishes to GitHub Pages.
- `run.yml`: a "Run workflow" button that runs a city from the Actions tab (keys as repository secrets).

## Rules this system keeps

- **Public data only.** News, company sites, public registries. No LinkedIn login or cookies; the optional Apify actors read public pages, and LinkedIn is otherwise only a search link a person clicks.
- **No prospect is contacted.** There is no send code; drafts are for a person to review.
- **Business-role data only** (DPDP): name, role and work email from a public source or Hunter, with the source kept next to each person.
- **Evidence for every signal**: a verbatim quote and a source link.
- **Free tiers**; every API response is cached and every paid call is charged against a cap.
- **Secrets stay out of git** (`.env`, `creds.json` and run data are ignored; CI checks).

## Known limits

- Named contacts are the weak spot: in the last full Pune run only 1 of 45 accounts got a named person, because of free-tier Apify and Hunter limits. Roles and LinkedIn search links are provided for the rest.
- The same company can appear under two names (for example "L&T Tech" and "L&T Technology Services") and some job-board pages give thin evidence.
- Seat and size figures come from public news and are rough; the caterer is left blank rather than guessed; there is no access to the InfinityBox CRM, so "already contacted" is a manual status.
- Apify's free LinkedIn actor is limited to 10 runs; the pipeline reports this as a failure rather than "nobody found".
- The public page's savings numbers are estimates from the visitor's own inputs and placeholder prices.

See [NEXT_30_DAYS.md](NEXT_30_DAYS.md) for how these are addressed.
