# Demo video script (target 4:40, hard limit 5:00)

Spoken text is in quotes (about 600 words: roughly 4:30 at a calm pace). Lines in brackets say what to show. Record at 1080p with the browser zoomed to 110-125% so text is readable. One take per section is fine; cut between sections.

## Before you press record (10 minutes)

1. **Wake the server:** open https://infinitybox-desk.onrender.com/ two minutes early so it is not asleep. Enter the access code once (type it off-camera; never show it).
2. **Have these tabs ready, in this order:** (1) dashboard Home, (2) the public page `/site/`, (3) the Google Sheet (tabs visible), (4) the GitHub repository's Actions tab, (5) `ARCHITECTURE.md` rendered on GitHub, (6) `AI_LOG.md` rendered on GitHub, (7) `NEXT_30_DAYS.md` rendered on GitHub.
3. **Start a Quick look for a city you have not run** (for example Hyderabad) in the dashboard a few minutes before recording, so it has finished when you show it. A run takes about 4 minutes; do not wait for one on camera.
4. **Prepare the test enquiry:** company "Demo Foods (test)", an email you own, city and role filled, consent ticked. Use obviously fake data.
5. **Hide anything private:** no `.env`, no keys, no access code on screen. The Pune list has one real contact name: use the Hyderabad list for the contacts part.
6. Open the sheet's `Leads` tab so the new row will be easy to see.

## 0:00 to 0:20: what it is [dashboard Home]

"This is the InfinityBox lead system. It finds companies about to need cafeteria warewashing or kitchen design, ranks them with a reason you can read, finds the right person, and drafts the email. A public calculator captures inbound enquiries. Nothing is ever sent: a person reviews every draft."

## 0:20 to 0:50: architecture and cost [ARCHITECTURE.md diagram]

"Five steps. Discover from news, tender and tracker pages. Extract signals, where every signal needs a quote copied word for word from its source, so the AI cannot invent events. Score with fixed rules, not the AI. Find contacts from websites, public LinkedIn pages and Hunter; emails are never generated. Draft from an approved playbook. On free tiers it costs nothing; scaled up with paid plans, about eight and a half thousand rupees a month."

## 0:50 to 2:10: the live run and a lead [dashboard]

"The hosted dashboard shows my remaining credits: it runs on a small capped allowance, so nobody can drain my accounts." [point at the credit bars]

"Find leads: pick a city, a Quick look, and it reports progress step by step. I ran Hyderabad earlier." [Leads, choose Hyderabad]

"Each lead has a score out of 100: fit, how fresh the trigger is, and how reachable the contact is." [open the top lead] "Here is how every point was earned, with the source link and the exact quote. Contacts are tiered: decision makers, day-to-day owners, and gatekeepers like a registrar, whom we only ask for an introduction. If no email is published, we say so."

[Write the email] "I pick a style and write a draft. It uses only approved facts about InfinityBox, and the checker flags unsupported claims, invented numbers and email addresses. The link goes to our calculator, tagged with the company. I edit, then Record in outbox: a placeholder that opens Gmail for a person to send."

## 2:10 to 2:35: the sheet is the database [Home sheet card, then the Google Sheet]

"The Google Sheet is the database. Runs are saved to it by city, so one city never overwrites another. I can load a city into the app or save the app's list back, and a restarted server reloads from it by itself." [show tabs: Accounts, Scores, Drafts]

## 2:35 to 3:40: the inbound page [public page]

"Now the inbound side." [start the 20-second tour for a few seconds] "The calculator uses dials: meals per day, then items per meal, and shows monthly spend in rupees from the visitor's own numbers. InfinityBox's own figures are labelled as reported."

[fill the test enquiry and submit] "I choose company with a cafeteria. Enquiries are routed by type: companies and institutions to warewashing, fit-out to kitchen design, caterers to partnerships."

[switch to the Google Sheet] "Here is the row in the Leads tab, with its queue." [dashboard, Website enquiries, Refresh] "The dashboard shows it, tagged Google Sheet, with the visit funnel per outreach batch. Tracking is anonymous: no cookies."

## 3:40 to 4:00: CI/CD and safety [GitHub Actions, then the repository]

"Every push runs the tests from a clean checkout, and the public page deploys only if its tests pass. Keys live in secrets, never in the repository, and CI fails if one slips in. Public data only, no LinkedIn login, nothing sent."

## 4:00 to 4:20: the AI log [AI_LOG.md]

"I built this with Claude Code, and Gemini works inside the product. The log records every mistake and how I caught it. For example, saving Bangalore deleted a Pune account because two cities shared a company id; I found it by checking the real sheet, and rows are now keyed by account and city."

## 4:20 to 4:40: limits and next 30 days [NEXT_30_DAYS.md]

"Honestly, named contacts are the weak spot: in the Pune run only one of 45 accounts got a named person, because of free-tier limits. Next: a daily run for all six cities, specialist scrapers with a verifier, paid data, a reviewer feedback loop, a survey-driven page, and drafts landing in Gmail, so the reviewer only checks sources and presses send. Thank you."

## If something goes wrong on camera

| Problem | What to do |
|---|---|
| Server is asleep or slow | Wait up to a minute and say "a free host wakes up on the first request"; cut the wait in editing. |
| Draft does not generate (credit cap reached) | Say it: "the demo allowance is capped, this is the guard working"; show a saved draft instead, or the five drafts in RESULTS_PUNE.md. |
| Enquiry row is slow to appear | Press Refresh on the dashboard (the sheet is re-read every 20 seconds) or reload the sheet tab. |
| A contact name shows | Cut that moment, or use another list. |

## Checklist for the submission email

- Repository link and Render link (access code sent separately).
- Video (under 5 minutes).
- Files to point to: README.md, RESULTS_PUNE.md (25 accounts, 5 drafts), ARCHITECTURE.md (diagram and rupee cost), AI_LOG.md, NEXT_30_DAYS.md.
