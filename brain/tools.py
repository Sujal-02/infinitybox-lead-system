"""Tools the Gemini agent can call. Infrastructure only: they fetch raw data, charge the free-trial budget, and remember
every text they return, so that save_lead can verify Gemini's quotes, emails and links against what the tools really
returned. No relevance scoring, no role matching, no ranking happens here: those are Gemini's decisions."""
import json
import re

from datetime import date

from src import budget, cfg, playbook
from src.discover import news, web
from . import scoring

SEEN: dict[str, str] = {}   # url -> every text the tools returned for it
EMAILS: set[str] = set()    # every email address that appeared in any tool output
URLS: set[str] = set()      # every URL that appeared in any tool output
LEADS: dict[str, dict] = {}  # company (lower) -> saved lead
MAX_LEADS = 25
CITY = {"name": ""}      # set by the agent run; used for deterministic scoring
EMAIL_STATUS: dict[str, str] = {}   # email -> status as reported by Hunter
MAX_AGE_DAYS = 120   # a trigger older than this is not "right now"
SEGMENTS = ["corporate", "caterer", "fitout", "institution"]
TRIGGERS = ["new_campus", "lease", "cafeteria_revamp", "tender", "caterer_renewal", "esg_plastic", "facilities_hiring"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _n(s: str) -> str:
    return " ".join(s.split())


def reset() -> None:
    SEEN.clear(), EMAILS.clear(), URLS.clear(), LEADS.clear(), EMAIL_STATUS.clear()


def _register(url: str, text: str) -> None:
    if url:
        SEEN[url] = SEEN.get(url, "") + " " + text
        URLS.add(url)
    EMAILS.update(e.lower().strip(".") for e in EMAIL_RE.findall(text))
    URLS.update(re.findall(r"https?://[^\s)\"'<>\]]+", text))


def _clean_err(e: Exception) -> str:
    msg = f"{type(e).__name__}: {e}"
    return re.sub(r"(api_key|token|key)=[^&\s]+", r"\1=***", msg)[:240]  # exceptions can carry URLs with secrets


def _out(obj, limit: int = 9000) -> str:
    return json.dumps(obj, ensure_ascii=False)[:limit]


def search_news(query: str) -> str:
    try:
        docs = news.parse(news._get(query))
    except Exception as e:
        return _out({"error": _clean_err(e)})
    rows = []
    for d in docs[:15]:
        _register(d.url, d.text)
        rows.append({"title": d.title, "date": d.date.isoformat(), "url": d.url})
    return _out({"results": rows})


def web_search(query: str, limit: int = 5, with_content: bool = False) -> str:
    try:
        res = web._search(query, min(int(limit), 8), scrape=bool(with_content))
    except Exception as e:
        return _out({"error": _clean_err(e)})
    rows = []
    for r in res:
        text = r.get("markdown") or r.get("description") or ""
        _register(r["url"], f"{r.get('title', '')}. {text}")
        rows.append({"title": r.get("title", ""), "url": r["url"], "text": text[:1500] if with_content else text[:300]})
    return _out({"results": rows})


def read_page(url: str) -> str:
    try:
        p = web.scrape(url)
    except Exception as e:
        return _out({"error": _clean_err(e)})
    _register(url, p["markdown"])
    URLS.update(p["links"])
    return _out({"url": url, "text": p["markdown"][:7000], "links": p["links"][:25]})


def hunter_domain_search(domain: str) -> str:
    from src.people import _hunter
    try:
        d = _hunter("domain-search", domain=domain, limit=10)
    except Exception as e:
        return _out({"error": _clean_err(e)})
    rows = []
    for e in d.get("emails", []):
        src = [s.get("uri", "") for s in e.get("sources", [])][:1]
        row = {"name": f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip(), "position": e.get("position"),
               "email": e["value"], "status": (e.get("verification") or {}).get("status") or "unverified",
               "confidence": e.get("confidence"), "linkedin": e.get("linkedin"), "source": src[0] if src else ""}
        rows.append(row)
        EMAIL_STATUS[row["email"].lower()] = row["status"]
        _register(row["source"], json.dumps(row))
    return _out({"domain": domain, "organization": d.get("organization"), "emails": rows})


def linkedin_find_company(company: str) -> str:
    try:
        res = web._search(f"{company} site:linkedin.com/company", 5, scrape=False)
    except Exception as e:
        return _out({"error": _clean_err(e)})
    rows = [{"title": r.get("title", ""), "url": r["url"]} for r in res if "linkedin.com/company/" in r["url"]]
    for r in rows:
        _register(r["url"], r["title"])
    return _out({"results": rows})


def linkedin_people(company_url: str, title_keywords: str) -> str:
    """Employees of a LinkedIn company page whose title matches a boolean query, e.g. '"facilities" OR "admin"'."""
    from src.people import _apify_run
    try:
        act = cfg.actor("people_alt")
        rows = _apify_run("people_alt", {**act["input"], "identifier": company_url, "job_title": title_keywords})
    except Exception as e:
        return _out({"error": _clean_err(e)})
    out = []
    for it in rows[:20]:
        loc = it.get("location")
        row = {"name": it.get("fullname", ""), "headline": it.get("headline", ""),
               "location": loc.get("full") if isinstance(loc, dict) else loc, "profile_url": it.get("profile_url", "")}
        out.append(row)
        _register(row["profile_url"], json.dumps(row, ensure_ascii=False))
    return _out({"company_url": company_url, "people": out})


def save_lead(**lead) -> str:
    """Validate against what the tools returned, then store with a code-computed score and a playbook-rendered email.
    Gemini fixes and retries on error."""
    problems = []
    company = (lead.get("company") or "").strip()
    if not company:
        problems.append("company is required")
    if lead.get("segment") not in SEGMENTS:
        problems.append(f"segment must be one of {SEGMENTS}")
    if lead.get("trigger_type") not in TRIGGERS:
        problems.append(f"trigger_type must be one of {TRIGGERS}")
    url, ev = lead.get("source_url", ""), lead.get("evidence", "")
    if url not in SEEN:
        problems.append("source_url was never returned by a tool; use a url from search_news/web_search/read_page")
    elif not ev.strip() or _n(ev) not in _n(SEEN[url]):
        problems.append("evidence is not a verbatim quote of the text the tools returned for source_url")
    try:
        age = (date.today() - date.fromisoformat(lead.get("event_date", ""))).days
        if age > MAX_AGE_DAYS or age < -14:
            problems.append(f"event_date is {age} days from today; a lead needs an event within {MAX_AGE_DAYS} days")
    except ValueError:
        problems.append("event_date must be YYYY-MM-DD")
    if lead.get("trigger_type") in TRIGGERS and ev and not scoring.trigger_supported(lead["trigger_type"], f"{ev} {lead.get('summary', '')}"):
        problems.append(f"trigger_type {lead['trigger_type']} is not supported by the evidence; choose the label the evidence actually shows")
    for c in lead.get("contacts") or []:
        if c.get("email") and c["email"].lower().strip() not in EMAILS:
            problems.append(f"email {c['email']} never appeared in any tool output; emails must come from Hunter or a page you read")
        if c.get("linkedin_url") and c["linkedin_url"] not in URLS:
            problems.append(f"linkedin_url {c['linkedin_url']} never appeared in any tool output")
        if not c.get("name") and not c.get("email"):
            problems.append("each contact needs a name or an email")
    rendered = None
    try:
        choice = playbook.Choice(**(lead.get("outreach") or {}))
        problems += playbook.validate(choice, lead.get("segment", ""), f"{ev} {lead.get('summary', '')}") if lead.get("segment") in SEGMENTS else []
        if not problems:
            rendered = playbook.render(company, lead["segment"], choice, playbook.link_for(company, lead["segment"], lead.get("city", "")))
    except Exception as e:  # missing/ill-typed outreach fields, or a rendering rule
        problems.append(f"outreach: {str(e)[:200]}")
    if problems:
        return _out({"saved": False, "problems": problems})
    key = company.lower()
    if key not in LEADS and len(LEADS) >= MAX_LEADS:
        return _out({"saved": False, "problems": [f"already {MAX_LEADS} leads saved; call finish"]})
    lead["draft"] = {"to_role": choice.to_role, "subject": rendered[0], "body": rendered[1]}
    lead["score"] = scoring.score_lead(lead, CITY["name"], EMAIL_STATUS)
    LEADS[key] = lead
    return _out({"saved": True, "leads_saved": len(LEADS), "remaining": MAX_LEADS - len(LEADS)})


TOOLS = {"search_news": search_news, "web_search": web_search, "read_page": read_page, "hunter_domain_search": hunter_domain_search,
         "linkedin_find_company": linkedin_find_company, "linkedin_people": linkedin_people, "save_lead": save_lead}

_S = {"type": "string"}
DECLARATIONS = [
    {"name": "search_news", "description": "Search Google News (India edition, last ~90 days). Free, no budget cost. Returns up to 15 headlines with date and url. Use plain keyword queries, e.g. 'Bangalore new campus seats cafeteria'.",
     "parameters_json_schema": {"type": "object", "properties": {"query": _S}, "required": ["query"]}},
    {"name": "web_search", "description": "Web search via Firecrawl (costs credits: 2 per search, +1 per result if with_content). Use for tenders, company sites, hiring pages, LinkedIn company pages.",
     "parameters_json_schema": {"type": "object", "properties": {"query": _S, "limit": {"type": "integer"}, "with_content": {"type": "boolean"}}, "required": ["query"]}},
    {"name": "read_page", "description": "Fetch one web page as text plus its links (1 credit). Use for contact/about pages, tender listings, articles.",
     "parameters_json_schema": {"type": "object", "properties": {"url": _S}, "required": ["url"]}},
    {"name": "hunter_domain_search", "description": "Hunter.io: people with work emails at a company domain, with title and Hunter's verification status. Scarce free quota: use only for your best leads.",
     "parameters_json_schema": {"type": "object", "properties": {"domain": _S}, "required": ["domain"]}},
    {"name": "linkedin_find_company", "description": "Find a company's LinkedIn page URL by name (costs web credits). Check the result really is that company.",
     "parameters_json_schema": {"type": "object", "properties": {"company": _S}, "required": ["company"]}},
    {"name": "linkedin_people", "description": "Employees of a LinkedIn company page whose job title matches a boolean query such as '\"facilities\" OR \"admin\"'. No location filter, so check each person's location. Costs Apify credit: use sparingly.",
     "parameters_json_schema": {"type": "object", "properties": {"company_url": _S, "title_keywords": _S}, "required": ["company_url", "title_keywords"]}},
    {"name": "save_lead", "description": "Save one finished lead (max 25). Quotes, emails and urls must come from tool outputs, and the trigger label must be supported by the evidence, or the save is rejected with reasons. You do not score the lead and you do not write the email: code scores it, and the email is assembled from an approved playbook using the ids you choose. Saving the same company again replaces it.",
     "parameters_json_schema": {"type": "object", "properties": {
         "company": _S, "segment": {"type": "string", "enum": SEGMENTS}, "trigger_type": {"type": "string", "enum": TRIGGERS},
         "event_date": {"type": "string", "description": "YYYY-MM-DD, within the last ~120 days"}, "summary": _S,
         "evidence": {"type": "string", "description": "verbatim quote from the text a tool returned for source_url"},
         "source_url": _S, "why_now": _S, "buyer_logic": {"type": "string", "description": "which role buys this at this kind of organisation and why"},
         "website": _S, "linkedin_company_url": _S,
         "contacts": {"type": "array", "items": {"type": "object", "properties": {
             "name": _S, "title": _S, "linkedin_url": _S, "email": _S,
             "email_source": {"type": "string", "description": "hunter | website | none"}, "note": {"type": "string"}}}},
         "outreach": {"type": "object", "description": "choices for the playbook email", "properties": {
             "to_role": _S, "event_phrase": {"type": "string", "description": "restates the trigger after 'Saw that <company> ...', using only words/numbers from the evidence"},
             "value_id": _S, "condition_id": _S, "cta_id": _S}, "required": ["to_role", "event_phrase", "value_id", "cta_id"]}},
         "required": ["company", "segment", "trigger_type", "event_date", "summary", "evidence", "source_url", "why_now", "buyer_logic", "outreach"]}},
    {"name": "finish", "description": "Call when done (25 leads saved, or nothing more worth doing). Give a short honest summary of what worked and what did not.",
     "parameters_json_schema": {"type": "object", "properties": {"summary": _S}, "required": ["summary"]}},
]
