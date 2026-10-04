"""Firecrawl (REST) for tender / career / news pages. Firecrawl handles robots and JS rendering."""
import re
from datetime import date
from urllib.parse import urlparse

import requests

from .. import budget
from ..cache import cached, retry
from ..cfg import env, yml
from ..models import Doc

API = "https://api.firecrawl.dev/v2"
MAX_CHARS = 8000
SKIP = ("linkedin.", "facebook.", "twitter.", "x.com", "wikipedia.", "instagram.", "youtube.", "naukri.", "glassdoor.",
        "shiksha.", "collegedunia.", "careers360.", "justdial.", "indiamart.", "crunchbase.", "zaubacorp.", "tofler.",
        "ambitionbox.", "indeed.", "bloomberg.", "reuters.", "economictimes.", "timesofindia.", "business-standard.",
        "hospitals-info.", "fleettogether.", "zospital.", "scribd.", "practo.", "lybrate.", "wikipedia.", "mapsofindia.")


def _search(query: str, limit: int, scrape: bool) -> list[dict]:
    body = {"query": query, "limit": limit, "country": "IN"}
    if scrape:
        body["scrapeOptions"] = {"formats": ["markdown"], "onlyMainContent": True}

    def go():
        budget.charge("firecrawl", 2 + (limit if scrape else 0))  # search 2 credits + 1 per scraped result
        r = requests.post(f"{API}/search", json=body, timeout=120,
                          headers={"Authorization": f"Bearer {env('FIRECRAWL_API_KEY')}"})
        r.raise_for_status()
        return r.json()
    data = cached("fc_search", [query, limit, scrape], lambda: retry(go, base=4)).get("data", {})
    return data.get("web", []) if isinstance(data, dict) else data


def fetch(city: str, per_query: int = 5, max_queries: int = 99) -> list[Doc]:
    docs = []
    for q in yml("cities")[city]["web_queries"][:max_queries]:
        for r in _search(q.format(city=city), per_query, scrape=True):
            text = (r.get("markdown") or r.get("description") or "")[:MAX_CHARS]
            if text:
                docs.append(Doc(url=r["url"], title=r.get("title", ""), text=text, date=date.today(), source="web"))
    return docs


def scrape(url: str) -> dict:
    """One page as {markdown, links} via Firecrawl (1 credit)."""
    def go():
        budget.charge("firecrawl", 1)
        r = requests.post(f"{API}/scrape", json={"url": url, "formats": ["markdown", "links"], "onlyMainContent": False},
                          timeout=120, headers={"Authorization": f"Bearer {env('FIRECRAWL_API_KEY')}"})
        r.raise_for_status()
        return r.json().get("data", {})
    d = cached("fc_scrape", url, lambda: retry(go, base=4))
    return {"markdown": d.get("markdown") or "", "links": d.get("links") or []}


NAME_NOISE = {"group", "india", "pune", "limited", "ltd", "pvt", "private", "the", "and", "company", "services", "technologies",
              "hospital", "university", "college", "institute", "centre", "super", "speciality"}


def name_words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) > 2 and w not in NAME_NOISE}


def find_domain(name: str, city: str) -> str:
    """First non-aggregator result whose host contains a distinctive word of the company name (a wrong site is worse than none)."""
    words = name_words(name)
    for r in _search(f"{name} {city} official website", 6, scrape=False):
        host = urlparse(r["url"]).netloc.lower().removeprefix("www.")
        if not any(s in host for s in SKIP) and any(w in host for w in words):
            return host
    return ""


def domain_for(a) -> str:
    """Account website: config/overrides.yaml, else a validated web search."""
    return (yml("overrides") or {}).get(a.id, {}).get("domain") or find_domain(a.name, a.city)
