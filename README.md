# InfinityBox Lead System

Finds companies likely to need cafeteria warewashing or kitchen design **right now**, ranks them with a visible reason, picks the role to approach, and writes **draft** emails. **Nothing is ever sent**; there is no send code.


## Deliverables
| What | Where |
|---|---|
| Working system, 30-minute setup | this README (below), `start.bat` / `start.sh` |
| **Live public page** (calculator and lead form) | https://sujal-02.github.io/infinitybox-lead-system/ |
| **Live team dashboard** (read-only snapshot, names and emails removed) | https://sujal-02.github.io/infinitybox-lead-system/dashboard/ |
| Live run on one city, ranked accounts with role, trigger, score and reason | Pune: the "Pune" list in the dashboard; `LEADS_*.md` reports and the Google Sheet in the working copy |
| Architecture and monthly cost in rupees | [ARCHITECTURE.md](ARCHITECTURE.md) |
| AI log (mistakes caught, tools, prompts, decisions) | [AI_LOG.md](AI_LOG.md) |
| Next 30 days | [NEXT_30_DAYS.md](NEXT_30_DAYS.md) |

The two live pages link to each other. They need GitHub Pages enabled for the repository (Settings, Pages, Source: GitHub Actions), which on a private repository needs a paid GitHub plan; the same pages also run from the app on your own computer (see Routes below).

## 30-minute setup (no coding)

1. **Start**: install Python 3.11+, then double-click `start.bat` (Windows) or run `./start.sh`. The first run sets up a private environment and creates `.env`.
2. **Keys**: open `.env` and fill in (all have free tiers; nothing is committed): `GEMINI_API_KEY` (aistudio.google.com), `FIRECRAWL_API_KEY` (firecrawl.dev), `HUNTER_API_KEY` (hunter.io), optional `APIFY_TOKEN` (leave empty to skip LinkedIn actors). Run `start` again.
3. **Use**: the lead desk opens in the browser. "Find leads" runs a city (about 3 to 5 minutes for a quick look); "Leads" shows the ranked list.
4. **Optional, Google Sheet** instead of a local workbook (one sheet holds the pipeline tabs, the website "Leads" and "Events"):
   1. console.cloud.google.com: create a project, then enable **Google Sheets API** and **Google Drive API** (APIs & Services -> Library).
   2. IAM & Admin -> Service accounts -> Create. No roles needed. Open it -> Keys -> Add key -> JSON. Save the file as `creds.json` in this folder (git-ignored). Copy the account's email (`...@...iam.gserviceaccount.com`).
   3. Create an empty Google Sheet, **Share** it with that email as Editor, and copy the id from its URL (between `/d/` and `/edit`) into `GSHEET_ID` in `.env`.
   4. `python -m src.run sheet_check` (says in plain words what is missing), then `python -m src.run init` (creates the tabs), then set `DRY_RUN=0`.
   **If your organisation blocks service-account keys**, skip steps 1 and 2 and use the Apps Script gateway: open the sheet -> Extensions -> Apps Script, paste `inbound/apps_script.gs`; Project settings -> tick "Show appsscript.json" and replace its content with `inbound/appsscript.json` (this limits the permission to **this one sheet**, no email, no other files); Script properties -> `API_TOKEN` (any long random string); Deploy -> Web app (execute as you, access Anyone). Put the `/exec` URL in `SHEET_WEBHOOK_URL` and the token in `SHEET_API_TOKEN` in `.env`. `sheet_check` and `init` then work the same. Anyone with the URL still needs the token to write.
   5. For website enquiries: the same Apps Script already handles the page's form and visit events (tabs Leads and Events). To get an email for each new enquiry, use the sheet's Tools -> Notification rules. In GitHub Actions use the secrets `SHEET_WEBHOOK_URL` and `SHEET_API_TOKEN` (or `GSHEET_ID` and `GOOGLE_CREDS_JSON` for a key).
5. **Terminal alternative**: `python -m src.run all --city Pune`.

Try it first without any keys or network: `python -m src.run all --city Pune --dry-run` (uses `tests/fixtures`).

## Commands
```
python -m src.run init
python -m src.run discover --city Pune
python -m src.run extract
python -m src.run score
python -m src.run people --top 40
python -m src.run draft --top 5
python -m src.run all --city Pune
```
Flags: `--dry-run`, `--limit N` (docs to process), `--no-cache`. Intermediate data lives in `data/`; API responses in `cache/`, so reruns are free.

## Where leads are looked for
Per city: Google News queries from `config/cities.yaml`, then (from `config/city_sources.yaml`) the city's own queries and, in a wide run, one query per tech park / micro-market, per recently seen expansion (a seed lead: kept only if a real article with a verbatim quote comes back), per institution and per local news site; plus Firecrawl searches and the fetchable tracker/lease/tender pages (`a: fetch`, best priority first, 2 pages in a limited run, 6 in a full run). Cities without a block in that file (Hyderabad, Chennai) still use the shared sources.

## How it decides
- **Signals** (new campus, lease, tender, ...) are pulled from Google News RSS and Firecrawl searches, then extracted by Gemini. A signal is kept only if its `evidence` is a verbatim substring of the fetched text.
- **Score** = fit (0-40) + trigger (0-45, decays with a 60-90 day half-life) + reach (0-15). Weights in `config/`. `reason` is built from the top parts.
- **People**: only for the top N accounts. Hunter finds business emails matching target roles; an email is stored only if Hunter marks it `valid`. Every account also gets a LinkedIn **search link** (manual fallback, no login).
- **Drafts** cite the trigger in the first sentence, are under 90 words, and are checked automatically. For corporates the draft gives something forwardable to their caterer.
- Change `Status` in Accounts/Drafts by hand (e.g. "contacted"); reruns keep it.

## Inbound calculator
`inbound/index.html` is static. Preview: `python -m http.server -d inbound 8000`, open http://localhost:8000.
Go live: (1) add a `Leads` tab (done by `init`); (2) from the sheet: Extensions > Apps Script, paste `inbound/apps_script.gs` and `inbound/appsscript.json` (one narrow permission, see step 4 of the setup), Deploy > Web app (execute as you, anyone can access); (3) paste the URL into `APPS_SCRIPT_URL` in `inbound/page.src.html`, run `python inbound/build.py`; (4) host `inbound/` on GitHub Pages.
Routing: corporate/institution -> warewashing, fitout -> kitchen design, caterer -> partner. Every calculator number is an estimate in the visible `CONFIG` block.

## Assumptions
- Seat/size estimates come from public headcount or news and are rough.
- Caterer is often unknown from public data, so it is left blank rather than guessed.
- No access to the InfinityBox CRM; "already contacted" is a manual status column.
- Source reliability varies; the LinkedIn search link is the fallback for people.
- Google News RSS gives headlines and snippets, not article bodies, so news evidence comes from those.
- **Leads view and filters:** `python -m src.run leads --city Pune --segment institution --trigger tender --min-score 30 --has-email --since-days 90 --source-kind tender --format md|csv|json --out file`. Each row has the account, score, best contact (LinkedIn profile, email + status, page that backs it), the company's LinkedIn page and every news/tender link behind the lead. The same view is the `Pipeline` sheet tab (with filter dropdowns).
- **Emails are never generated.** Only what Hunter returned (stored with its status, e.g. `valid`, `accept_all`) or an address published on the org's own website (status `published`, free-mail skipped).
- **Contact hierarchy** (`config/hierarchy.yaml`, `src/hierarchy.py`): per kind of organisation (corporate, manufacturing, education, hospital, government, caterer, fit-out) titles are tiered: tier1 decision maker (0.9), tier2 day-to-day owner (0.7), tier3 gatekeeper (0.4, e.g. a registrar: used only to ask for an introduction), plus an exclude list (professors, surgeons, engineers, finance ...). A trigger boosts matching roles (tender favours purchase, new campus favours facilities/real estate). Relevance >= 0.6 is a real target; the engine returns a primary and a secondary target, else one gatekeeper plus any relevant office found on the site (tier `office`, e.g. a Hostel Office page with no published contact). `python -m src.run contacts --account <id>` prints every candidate with its tier and the reason.
- **Apify actors:** `config/actors.yaml` lists `people` (harvestapi, has a location filter, refused after 10 free runs) and `people_alt` (apimaestro, no location filter so results are filtered to the city afterwards; works on the free plan but only reaches staff of India-centric employers, not the India staff of multinationals). The pipeline tries them in order and skips a refused one for the rest of the run.
- **Gemini resilience:** `GEMINI_MODELS` (default gemini-3.8-flash, gemini-2.5-flash, gemini-2.5-flash-lite) are tried in turn, with one short retry on transient errors (429/5xx and the intermittent 403).
- **Apify free plan (old note):** the LinkedIn actor allows only 10 free runs; after that runs return nothing and the log says so. The pipeline now reports this as a failure (it does not mean nobody was found).
- **Contact order:** org website first (Firecrawl; cheapest, good for universities and small firms), then Apify LinkedIn, then Hunter only if no email was found. Pin a wrong match in `config/overrides.yaml`.
- **POC engine** (`src/people.py`): per top-N account it merges Apify LinkedIn results (actor `harvestapi/linkedin-company-employees`, no cookies) and Hunter, keeps the 2 people whose title best fits the segment's target roles, and finds a verified email for the best one only. Set `APIFY_TOKEN`, then run `python -m src.run apify_test --top 5` once to confirm the actor's output fields before trusting it (`verified: false` in `config/actors.yaml` until then). Any actor not listed there is refused.
- **Not built yet: Apify jobs actor** (`jobs` in `config/actors.yaml` is still a placeholder).
- Each source fails independently; a per-source count is printed at the end of every run.

## Tests
`python -m pytest -q` (no keys needed; Apps Script test needs node).

See `ARCHITECTURE.md` for the data flow and monthly cost, `AI_LOG.md` for AI mistakes caught.

## Free-trial budget
`config/budgets.yaml` caps what one run and one month may spend per service (Firecrawl credits, Hunter searches, Apify runs, Gemini requests). Only real (uncached) calls are charged; a cap stops that source with a message and the run continues. `python -m src.run quota` shows live balances from each provider next to what this project has spent; every run ends with a spend line. Set the caps below your real balance.


## The app (for non-technical users)
`start.bat` / `./start.sh` (or `python -m app`) opens http://127.0.0.1:8765 with five tabs: Home (counts, how it works, free credits left), Leads, Find leads (pick a city and size, watch progress), Website enquiries (funnel and enquiries) and Outbox. In Leads, pick a list, click a company, and you see: why it is a lead, how the score is made (plain-English points, calculated by code, not the AI), the news/tender sources with the exact quote and a link, who to contact (with the reason, never a guessed email), and "Write the email".
- **Writing the email:** choose one of 10 styles (`config/templates.yaml`; each asks for three short paragraphs: why the trigger matters to them, how InfinityBox works for that kind of organisation, what a first call would cover), choose who it is for, optionally add a note, press "Write a draft". Gemini writes it using only the approved facts and forbidden words in `config/playbook.yaml`; the app adds the greeting (if a name is known), a link to the public calculator page and a `[Your name]` sign-off. The link (set in `config/playbook.yaml` under `link.url`) is added by code, never by the model, pre-filled with the company, segment and city and tagged `utm_campaign=<city>-<yyyymm>` so visits show up in the Website enquiries tab; deleting it is flagged. Edit freely: unsupported claims, invented numbers, email addresses and over-long text are flagged live and block Send.
- **Send is a placeholder.** `app/mailer.py` delivers nothing: it records the message in the Outbox (`app_data/outbox.json`) and offers a pre-filled Gmail compose link so a person presses send. To make it real later, replace `deliver()` in `app/mailer.py` with the Gmail MCP/API call; nothing else changes.


## The public page (inbound)
`inbound/index.html` is a single static page in a hand-painted-truck style ("Reuse OK Please"): hero with an animated truck, how the loop works, a calculator built from **radial dials**, a lead form on the truck's tailgate, who it is for, and an FAQ. It is built from `inbound/page.src.html` + `inbound/assets/sprite.svg` by `python inbound/build.py` (edit the source, rebuild). Plain HTML/CSS/JS, about 60 KB, no build tooling, works on phones.
- **Calculator:** step 1 is a draggable meals dial (log scale, 100 to 20,000) with quick-pick chips plus chips for working days and city; step 2 is a swipeable carousel with one dial per item (0 to 5 per meal) and a tap-to-edit price; step 3 is an animated ring (Items or Rupees) with a truck that loads the biggest items. Dials support mouse, touch and keyboard (arrows, Home, End), snap with a short glide, and never wrap past the ends. Panes slide between steps; all motion is switched off for `prefers-reduced-motion`.
- **Honest numbers:** every figure is the visitor's own input times editable placeholder prices (`calc.js`, shown on the page). The only InfinityBox figures (30% water, 25% electricity, 40% single-use waste) are labelled "InfinityBox reports", linked to getinfinitybox.com, and not applied to the visitor's numbers.
- **Outreach links** can prefill the page: `?m=2000&city=Pune&c=Acme&s=caterer&utm_source=mail&utm_campaign=batch1`.
- **Where a lead lands:** with `python -m app`, open http://127.0.0.1:8765/site/ and submit; the lead appears in the app's "Inbound leads" tab, routed by segment (corporate/institution -> warewashing, fitout -> kitchen design, caterer -> partner). To send leads to a Google Sheet instead, deploy `inbound/apps_script.gs` and paste its URL into `APPS_SCRIPT_URL` at the top of the page script. Host the `inbound/` folder on GitHub Pages.
- **Spam protection:** hidden honeypot field and a 3-second minimum fill time; consent box required.

## Routes (what lives where)
| Where | Public page (frontend) | Team dashboard |
|---|---|---|
| **On your computer** (`start.bat`) | http://127.0.0.1:8765/site/ | http://127.0.0.1:8765/ (also `/dashboard/`). Full desk: find leads, write emails, outbox, enquiries. |
| **GitHub Pages** | `https://<user>.github.io/<repo>/` | `.../dashboard/`. Read-only snapshot of the lead lists with names, emails and LinkedIn profiles removed. |

The two link to each other: the page footer has "Team dashboard", and the desk header has "Public page". Refresh the snapshot after a new run with `python -m app.export_static`, commit `dashboard/`, push.

## Making the Pages dashboard fully functional (capped credits)
GitHub Pages only serves files, so the dashboard on Pages talks to a small server that runs this same app (`Dockerfile`, `render.yaml`). Without a server configured it stays a read-only snapshot.
1. **Deploy the server** (free): on render.com choose New, Blueprint, pick this repo. It reads `render.yaml`. When asked, fill the keys (`GEMINI_API_KEY`, `FIRECRAWL_API_KEY`, `HUNTER_API_KEY`, optional `APIFY_TOKEN`, optional `SHEET_WEBHOOK_URL` and `SHEET_API_TOKEN`) and choose an `ACCESS_CODE`. Any host that runs Docker works the same way.
2. **Connect Pages to it**: in the GitHub repo, Settings, Secrets and variables, Actions, Variables, add `API_URL` = the server's `https://...onrender.com` address. Run the `deploy-inbound-page` workflow. If your Pages address is not `https://sujal-02.github.io`, change `ALLOWED_ORIGIN` in `render.yaml` to it.
3. **Open** `.../dashboard/`. It asks for the access code once per browser tab, then everything works: Find leads, Write the email, outbox.
**How credits are capped:** the server runs with `BUDGET_PROFILE=demo`: a smaller allowance (`demo:` in `config/budgets.yaml`, for example 100 Gemini requests and 6 Hunter searches a month), only the Quick look size, one run at a time, and the Home tab shows what is left. A wrong access code is rate limited, and the public-page endpoints are switched off on the server. A free host sleeps when idle (the first request can take a minute) and forgets its lead lists when it restarts; the lists are rebuilt by Find leads, or kept in the Google Sheet when `SHEET_WEBHOOK_URL` is set.

## CI/CD (`.github/workflows/`)
- `ci.yml`: on every push and pull request, runs the tests and checks that the built pages match their sources. In a public repo it also fails if a key file or key-shaped string is tracked.
- `pages.yml`: on a push to `main` that touches the page or dashboard, runs the page tests, then publishes the page, `/dashboard/` and a 404 page to GitHub Pages. Pages needs a public repo or a paid GitHub plan (it does not work for private repos on the free plan).
- `run.yml`: manual "Run workflow" button to run a city from the Actions tab (needs the keys as repository secrets).
