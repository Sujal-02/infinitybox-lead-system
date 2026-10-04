# Next 30 days: from prototype to an autonomous lead system

**Where we are.** A working, deployed prototype: one button (or command) finds trigger-backed leads in a city, ranks them with a visible reason, finds contacts, and writes per-company drafts that a person edits. It runs as a hosted dashboard (Render, behind an access code, capped credits) with a Google Sheet as its database, plus a public calculator page whose enquiries and visit funnel land in the same sheet. Nothing is ever sent. A full Pune run produced 45 accounts and 5 drafts ([RESULTS_PUNE.md](RESULTS_PUNE.md)); known limits are listed at the end.

**Where we are going (day 30).** Every morning a scheduled run covers all six cities and puts a small, ranked batch of **Gmail drafts** in a shared mailbox. A reviewer opens each lead card, checks the news and source links, edits if needed, and presses **Send** in Gmail. That human send stays on purpose. Everything before it runs without anyone touching it.

```
daily 05:30 cron (per city, staggered)
  specialist scrapers (agents) -> evidence verifier -> dedupe vs. history -> score -> contact finder
        -> draft writer (playbook) -> Gmail API drafts.create (label "InfinityBox/To review")
  reviewer (15 min/city/day): lead card = trigger, quote, source links, score reason, contacts -> edit -> Send in Gmail
  outcomes (sent, replied, meeting, bad lead) -> feedback table -> weekly score and playbook tuning
```

## Week 1 (days 1-7): make it run by itself, and trustworthy
| Day | Work | Done when |
|---|---|---|
| 1-2 | Move the pipeline to a scheduled job (GitHub Actions cron to start, small VPS if runs exceed 6 hours/month). All keys as secrets; rotate the Hunter key. | A run starts at 05:30 with nobody present and reports to a channel |
| 2-3 | Persistent history: a table of accounts with state (`new`, `seen`, `drafted`, `sent`, `replied`, `rejected`). A lead is never shown twice unless something new happens. | Same company never appears on two days without a new trigger |
| 3-4 | Fix the known quality gaps: merge aliases (L&T Tech / L&T Technology Services, SBI), drop weak evidence (job-board stubs like "Compass Group, Pune"), check the city against the source, treat undated pages as undated instead of "today". | Re-run Pune: no duplicates, no stub evidence |
| 5 | Budget and health dashboard (credits per vendor, failures per source, runs per day) and alerts when a source goes dark. | A broken source is noticed within a day |
| 6-7 | Run all six cities for a week in "shadow mode" (no drafts to Gmail yet); reviewer scores 20 leads per city as good / maybe / bad. | A labelled set of about 120 leads to measure against |

## Week 2 (days 8-14): multi-agent scrapers and paid data
Replace the single discovery pass with specialists. Each has one job, one budget, and returns only evidence-backed signals:
- **News and GCC agent:** news, GCC trackers, city micro-market queries (already in `city_sources.yaml`).
- **Tender agent:** GeM and state tender portals (Maharashtra, Karnataka, Telangana, Tamil Nadu, Delhi): housekeeping, canteen, kitchen, dish-wash tenders.
- **Lease and real-estate agent:** lease transactions, REIT tenant lists, new-building completions.
- **Jobs agent:** facilities, workplace and admin hiring (a real signal, but only with the company's own careers page as evidence).
- **ESG agent:** BRSR filings and single-use-plastic commitments.
- **Institutions agent:** hospitals, universities, hostels opening or extending.
- **Verifier agent:** a second, independent model call that reads the quote and the page and must say yes before a signal is accepted. A coordinator merges, dedupes and hands the survivors to scoring.

**Subscriptions to buy** (prices are estimates at today's list prices and ₹90 per US$; confirm at purchase):

| Item | Why | ~₹ / month |
|---|---|---|
| Firecrawl paid plan | 10x the page reads for tender and tracker pages | 7,000-9,000 |
| Hunter paid plan (or Apollo) | Verified emails for the top 60-100 accounts per day | 4,500-13,000 |
| Apify paid plan | Reliable LinkedIn-company actors without the free-run limit (public data only, no login) | 2,500-5,000 |
| Gemini paid tier | Higher limits; cost stays small at about 150 accounts a day | 1,500-3,000 |
| Small VPS + domain mailbox (Google Workspace) | Cron host, and the sending identity | 1,500-2,500 |
| **Total** | | **about 17,000-33,000** |

Decision rule: buy a tier only after the free one has been the proven limit for three days, and track cost per qualified lead from day one.

## Week 3 (days 15-21): lead quality and the inbound page
**Lead quality**
- Reviewer verdicts feed a `feedback` table. Once there are about 300 labelled leads, fit the score weights against "accepted by reviewer" (still a transparent formula, just tuned).
- Segment playbooks: separate drafts and contact rules for GCC offices, hospitals/universities, caterers and fit-out firms; one proven number or client name per segment added to `playbook.yaml` only when the business confirms it.
- Contact depth: named decision-maker plus one backup per account; a "route through the caterer" path when the cafeteria is outsourced.
- Weekly "bad lead" review: every rejected lead adds a negative rule (for example, "job-board stub", "wrong city", "government dept with no kitchen").

**Inbound page, after a survey**
- Before changing the page: 8-10 short calls with cafeteria owners, facilities heads and caterers (what they pay today, who decides, what they would trust), plus a one-question poll on the result screen ("What would make you ask for a site visit?").
- Read the funnel the page already records (visited, started, items, result, form opened, sent) per outreach batch.
- Then change the page: copy in their words, a version for caterers and one for institutions, WhatsApp as a second contact option, Hindi and one regional language, and the three SEO pages expanded into a short guide.
- A/B one thing at a time through the `utm_campaign` tag already in every draft link.

## Week 4 (days 22-30): autonomy, Gmail drafts and go-live
- **Gmail drafts:** the pipeline creates drafts with the Gmail API (`drafts.create`, scope `gmail.compose`, never `gmail.send`) in a shared mailbox under the label "InfinityBox/To review". Each draft carries a link to its lead card (news, quotes, sources, score reason). The reviewer edits and sends from Gmail.
- **Review screen:** the Lead desk gets a "Today" queue: one card per draft with the source links up front, and one-click verdicts (good / bad / wrong person / not now) that feed the feedback table.
- **Sending safety (before the first real send):** a separate sending subdomain, SPF/DKIM/DMARC set up, warm-up over 2-3 weeks, at most 30 sends a day per mailbox, an unsubscribe line, a suppression list, and automatic stop if bounces pass 3%. No LinkedIn automation of any kind; LinkedIn stays a link a person clicks.
- **Controls:** a kill switch (one setting stops creating drafts), a full audit log (what was found, from which source, who approved), and a weekly digest.
- **Day 28-30:** one week of live operation with a single reviewer, then a short retrospective and a go/no-go on adding more mailboxes.

## How we will know it works (targets for day 30)
| Measure | Target |
|---|---|
| Runs completed on schedule | 95% of days |
| Drafts waiting each morning | 20-30 across six cities |
| Reviewer accepts the lead as real and relevant | at least 70% |
| Review time | under 15 minutes per city per day |
| Duplicate or wrong-city leads | under 5% |
| Bounce rate of sent emails | under 3% |
| Reply rate / meetings booked | measured from week 4; set the goal after the first 100 sends |
| Cost per accepted lead | tracked daily; target set after week 2 |

## Risks and how they are handled
- **Source blocks or layout changes:** every source has a health check; a dead source alerts instead of silently returning nothing.
- **Wrong or invented facts in a draft:** the evidence check, the playbook (only approved claims) and the reviewer all stand between a draft and a send.
- **Platform terms and deliverability:** public data only, no login or automation on LinkedIn, no scraping behind logins, robots respected; sending only after warm-up and from a dedicated subdomain.
- **Privacy (DPDP):** business-role data only, with the source kept next to each person; people can be removed on request; nothing personal beyond a work contact.
- **Over-trusting automation:** the send button stays human until the accept rate and bounce rate have held for a month.

## What we know is weak today
- Contacts: only one of 45 Pune accounts got a named person in the last full run, because of free-tier Apify limits and Hunter's small allowance.
- The same company can appear under two names; some job-board pages give thin evidence; the dated "today" fallback can overstate recency on tracker pages.
- Contact discovery for multinationals' India offices is limited by what public pages show.
- The inbound page has not been tested with real visitors yet; its copy is our best guess until the survey.
