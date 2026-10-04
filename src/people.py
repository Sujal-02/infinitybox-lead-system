"""Targeted POC engine. For one account: classify the organisation, gather candidates from the cheapest sources first,
score each against the contact hierarchy (src/hierarchy.py), and return a primary + secondary target, or, failing that,
one gatekeeper clearly labelled "route, not the buyer".
Sources (each fails independently): the org's own website (Firecrawl), Apify LinkedIn actor (no cookies, allowlisted),
Hunter (only when no email has been found yet).
Emails are never generated: only what the website or Hunter returned, with its status and the page that backs it.
Business-role data only (DPDP): name, title, public profile URL, work email."""
import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

import requests

from . import budget, cfg, hierarchy
from .cache import cached, retry
from .cfg import env, yml
from .contacts import from_website
from .discover import web
from .models import Account, Person

HUNTER = "https://api.hunter.io/v2"
LOCATIONS = {"NCR": ["Gurugram", "Noida", "Delhi"], "Bangalore": ["Bangalore", "Bengaluru"], "Hyderabad": ["Hyderabad", "Secunderabad"],
             "Mumbai": ["Mumbai", "Navi Mumbai", "Thane"], "Chennai": ["Chennai"]}  # LinkedIn location filter text per city
SENIOR = ("head", "director", "chief", "vp", "dean", "general manager", "controller")


def _hunter(path: str, **params) -> dict:
    def go():
        budget.charge("hunter", 1)
        r = requests.get(f"{HUNTER}/{path}", params={**params, "api_key": env("HUNTER_API_KEY")}, timeout=30)
        r.raise_for_status()
        return r.json().get("data", {})
    return cached("hunter_" + path, params, lambda: retry(go))


def search_link(a: Account, title: str) -> str:
    return yml("roles")["search_link"].format(company=quote(a.name), title=quote(title), city=quote(a.city))


def locations(city: str) -> list[str]:
    return LOCATIONS.get(city, [city])


def _scored(a: Account, title: str, triggers) -> hierarchy.Rel:
    return hierarchy.relevance(title, a.org_kind, triggers)


def _map_item(item: dict) -> dict:
    """Normalise one Apify result row (fields confirmed by a real run on 2026-10-03)."""
    pos = item.get("currentPosition") or item.get("currentPositions") or []
    pos = pos[0] if isinstance(pos, list) and pos else (pos if isinstance(pos, dict) else {})
    name = item.get("fullName") or item.get("name") or f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
    return {"name": name.strip(),
            "title": pos.get("position") or pos.get("title") or item.get("headline") or item.get("position") or "",
            "url": item.get("linkedinUrl") or item.get("profileUrl") or item.get("url") or ""}


def linkedin_company_url(a: Account) -> str:
    """Company page: manual override, else a web-search hit whose slug matches most of the company's name words."""
    forced = (yml("overrides") or {}).get(a.id, {}).get("linkedin")
    if forced:
        return forced
    words = web.name_words(a.name)
    for r in web._search(f"{a.name} {a.city} site:linkedin.com/company", 5, scrape=False):
        u = r.get("url", "")
        if "linkedin.com/company/" not in u or not words:
            continue
        slug = u.split("/company/")[1].split("/")[0].split("?")[0].lower()
        toks = [t for t in slug.split("-") if len(t) > 2 and t not in web.NAME_NOISE and not t.isdigit()]
        matched = {w for w in words if any(w in t for t in toks)}
        extras = [t for t in toks if not any(w in t for w in words)]
        if len(matched) >= max(1, round(0.6 * len(words))) and len(extras) <= 1:  # rejects "sinhgad-academy-...-pune-university"
            return f"https://www.linkedin.com/company/{slug}"
    return ""


class ApifyError(RuntimeError):
    fatal = True  # a quota/limit message will not clear on retry


def check_run(run) -> None:
    """An actor run can end SUCCEEDED with zero items and a status message explaining why (e.g. the free-plan run
    limit). Treat that as a failure so it is reported and never cached as "no people found"."""
    msg = getattr(run, "status_message", "") or ""
    status = str(getattr(run, "status", ""))
    if "limit" in msg.lower() or "exceeded" in msg.lower() or ("SUCCEEDED" not in status and "READY" not in status):
        raise ApifyError(f"apify run {status}: {msg or 'no status message'}")


def _apify_run(key: str, run_input: dict) -> list[dict]:
    from apify_client import ApifyClient
    act = cfg.actor(key)  # refuses anything not allowlisted

    def go():
        budget.charge("apify", 1)
        c = ApifyClient(env("APIFY_TOKEN"))
        run = c.actor(act["id"]).call(run_input=run_input, run_timeout=timedelta(seconds=180),
                                      max_total_charge_usd=Decimal("0.50"))  # hard spend cap per run
        check_run(run)
        ds = getattr(run, "default_dataset_id", None) or run["defaultDatasetId"]
        return list(c.dataset(ds).iterate_items())
    return cached("apify_people", [act["id"], run_input], lambda: retry(go, tries=1))  # a limit error will not fix itself: no retry


_refused: set[str] = set()  # actors refused during this run


def _title_from_headline(h: str) -> str:
    """'Facility Manager at Tata Consultancy Services' -> 'Facility Manager' (the company name must not leak into role matching)."""
    return re.split(r"\s+(?:at|@)\s+", h or "", maxsplit=1)[0].strip(" |-")


def _in_city(item: dict, city: str) -> bool:
    loc = item.get("location")
    text = (loc.get("full") if isinstance(loc, dict) else str(loc or "")).lower()
    return any(c.lower() in text for c in locations(city))


def _apify_people(a: Account, key: str, titles: list[str], triggers) -> list[Person]:
    act = cfg.actor(key)
    if act["adapter"] == "harvestapi":
        run_input = {**act["input"], "companies": [a.linkedin_url], "jobTitles": titles[:12], "locations": locations(a.city),
                     "maxItems": act["max_items_per_company"]}
        rows = [(m["name"], m["title"], m["url"]) for m in map(_map_item, _apify_run(key, run_input))]
    else:  # apimaestro: boolean job_title query, no location filter, so keep only people in the city afterwards
        words = hierarchy.query_words(a.org_kind)
        run_input = {**act["input"], "identifier": a.linkedin_url, "job_title": " OR ".join(f'"{w}"' for w in words)}
        rows = [(it.get("fullname", ""), _title_from_headline(it.get("headline", "")), it.get("profile_url", ""))
                for it in _apify_run(key, run_input) if _in_city(it, a.city)]
    out = []
    for name, title, url in rows:
        if name and title:
            r = _scored(a, title, triggers)
            out.append(Person(account_id=a.id, role=title, name=name.strip(), profile_url=url, source="apify:" + act["id"],
                              source_url=a.linkedin_url, role_match=r.score, tier=r.tier, why=r.why))
    return out


def from_apify(a: Account, titles: list[str], stats: dict, triggers=()) -> list[Person]:
    """LinkedIn people via allowlisted no-cookie actors, tried in order; the next one is used if the first is refused
    (e.g. the free-plan run limit) so one actor's quota does not end contact discovery."""
    if not env("APIFY_TOKEN"):
        return []
    a.linkedin_url = a.linkedin_url or linkedin_company_url(a)
    if not a.linkedin_url:
        stats["apify_no_company_url"] = stats.get("apify_no_company_url", 0) + 1
        return []
    last = None
    for key in ("people", "people_alt"):
        if key in _refused:  # already refused earlier in this run: do not spend another attempt on it
            continue
        try:
            out = _apify_people(a, key, titles, triggers)
            stats["apify_people"] = stats.get("apify_people", 0) + len(out)
            return out
        except (ApifyError, budget.BudgetExceeded) as ex:
            last = ex
            _refused.add(key)
            stats[f"{key}_unavailable"] = stats.get(f"{key}_unavailable", 0) + 1
    raise last or ApifyError("no Apify actor available")


def _hunter_person(a: Account, e: dict, r: hierarchy.Rel) -> Person:
    ver = (e.get("verification") or {}).get("status") or "unverified"
    srcs = e.get("sources") or []
    return Person(account_id=a.id, role=e.get("position") or "", role_match=r.score, tier=r.tier, why=r.why, source="hunter",
                  name=f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip(), profile_url=e.get("linkedin") or "",
                  email=e["value"], email_status=ver, source_url=srcs[0].get("uri", "") if srcs else "",
                  evidence=f"Hunter confidence {e.get('confidence')}")


def from_hunter(a: Account, titles: list[str], stats: dict, triggers=()) -> list[Person]:
    """People Hunter lists for the domain, kept if the hierarchy finds them relevant. Emails stored exactly as returned."""
    if not env("HUNTER_API_KEY"):
        return []
    a.domain = a.domain or web.domain_for(a)
    if not a.domain:
        return []
    out = []
    for e in _hunter("domain-search", domain=a.domain, limit=10).get("emails", []):
        r = _scored(a, e.get("position") or "", triggers)
        if r.score >= 0.3:
            out.append(_hunter_person(a, e, r))
    stats["hunter_people"] = stats.get("hunter_people", 0) + len(out)
    return out


def hunter_email_for(a: Account, p: Person, stats: dict) -> None:
    """Hunter email-finder for one named person; accept whatever Hunter returns (with its status)."""
    first, _, last = p.name.partition(" ")
    if p.email or not (a.domain and last and env("HUNTER_API_KEY")):
        return
    d = _hunter("email-finder", domain=a.domain, first_name=first, last_name=last)
    if d.get("email"):
        p.email, p.email_status = d["email"], (d.get("verification") or {}).get("status") or "unverified"
        p.source += "+hunter"
        srcs = d.get("sources") or []
        p.evidence = (p.evidence + " | " if p.evidence else "") + f"Hunter score {d.get('score')}"
        p.source_url = p.source_url or (srcs[0].get("uri", "") if srcs else "")
        stats["hunter_emails"] = stats.get("hunter_emails", 0) + 1


def _key(p: Person) -> str:
    return re.sub(r"\W", "", p.name.lower()) or p.email or p.profile_url


def merge(cands: list[Person]) -> list[Person]:
    """One row per person (by name/email); keep the best relevance and fill blanks from the other source."""
    by: dict[str, Person] = {}
    for p in sorted(cands, key=lambda x: -x.role_match):
        k = _key(p)
        if k not in by:
            by[k] = p
            continue
        b = by[k]
        b.profile_url, b.email, b.email_status = b.profile_url or p.profile_url, b.email or p.email, b.email_status or p.email_status
        b.source_url, b.evidence = b.source_url or p.source_url, b.evidence or p.evidence
        if p.source not in b.source:
            b.source += "+" + p.source
    return sorted(by.values(), key=lambda p: (-p.role_match, -bool(p.email), -any(k in p.role.lower() for k in SENIOR)))


def select(cands: list[Person], keep: int = 2) -> list[Person]:
    """Primary + secondary targets (relevance >= 0.6). If there are none, the best gatekeeper, flagged as route-only."""
    ranked = merge(cands)
    targets = [p for p in ranked if p.role_match >= hierarchy.TARGET][:keep]
    if targets:
        return targets
    gate = next((p for p in ranked if p.tier == "tier3"), None)
    note = " | no decision maker found: use to ask for an introduction to the cafeteria/facilities owner"
    if gate and note not in gate.why:
        gate.why += note
    return ([gate] if gate else []) + [p for p in ranked if p.tier == "office"][:2]  # relevant offices with no published contact


def discover(a: Account, stats: dict, triggers=()) -> list[Person]:
    """Every scored candidate, cheapest sources first; later sources only run when earlier ones found no target."""
    a.org_kind = a.org_kind or hierarchy.classify(a.segment, a.name)
    titles = hierarchy.titles_for(a.org_kind)

    def run(src, cands):
        try:
            return cands + src(a, titles, stats, triggers)
        except Exception as ex:  # skip this source, keep going; never print URLs (they carry keys)
            resp = getattr(ex, "response", None)
            why = str(ex)[:140] if isinstance(ex, ApifyError) else getattr(resp, "status_code", "")  # no URLs: they carry keys
            print(f"{src.__name__} failed for {a.name}: {type(ex).__name__} {why}")
            stats[f"{src.__name__}_failed"] = stats.get(f"{src.__name__}_failed", 0) + 1
            return cands

    def hit(c):
        return any(p.role_match >= hierarchy.TARGET for p in c)

    # non-corporates (universities, hospitals, small firms) publish contacts on their site: try that first
    order = (from_website, from_apify) if a.segment not in ("corporate",) else (from_apify, from_website)
    cands = run(order[0], [])
    if not hit(cands):
        cands = run(order[1], cands)
    if not hit(cands):  # Hunter last, only when no real target was found by the cheaper sources
        cands = run(from_hunter, cands)
    named = next((p for p in select(cands) if p.name and p.role_match >= hierarchy.TARGET and not p.email), None)
    if named:  # a named target without an email: ask Hunter's email-finder once
        try:
            hunter_email_for(a, named, stats)
        except Exception as ex:
            print(f"hunter_email_for failed for {a.name}: {type(ex).__name__}")
    return merge(cands)


def find_people(a: Account, stats: dict, keep: int = 2, triggers=()) -> list[Person]:
    a.org_kind = a.org_kind or hierarchy.classify(a.segment, a.name)
    links = []  # manual LinkedIn searches for the top tier1 / tier2 titles (a human fallback, no scraping)
    for t in hierarchy.titles_for(a.org_kind, ("tier1", "tier2"))[:1] + hierarchy.titles_for(a.org_kind, ("tier2",))[:1]:
        links.append(Person(account_id=a.id, role=t.title(), profile_url=search_link(a, t), source="linkedin-search-link",
                            tier="search", why="manual search link", purpose="manual lookup link, no personal data"))
    if cfg.dry:
        return links
    return links + select(discover(a, stats, triggers), keep)
