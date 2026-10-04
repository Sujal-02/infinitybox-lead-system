"""City-level discovery driven by config/city_sources.yaml (the `usage` notes in that file describe the plan).

1. News queries (free, Google News RSS): the city's own query list; with `wide` also one query per tech park / micro-market,
   per recently seen expansion (a seed lead, confirmed only if a real article with evidence comes back), per institution
   and per local news site (`site:` search).
2. Page reads (Firecrawl credits): sources marked `a: fetch` (GCC trackers, lease data, tenders), best priority first.
Cities with no block in the file (Hyderabad, Chennai) still get the shared fetchable sources."""
import re
from datetime import date

from .. import cfg
from ..models import Doc
from . import web

KEY = {"Bangalore": "bengaluru", "Pune": "pune", "Mumbai": "mumbai", "NCR": "gurugram"}  # cities.yaml name -> city_sources.yaml key
PRIORITY = {"h": 0, "m": 1, "l": 2}
SITE = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", re.I)


def _block(city: str) -> dict:
    return cfg.yml("city_sources").get(KEY.get(city, ""), {})


def _name(raw: str) -> str:
    """Entry names carry notes in brackets ("Hinjewadi (Phase 1-3)"); a search needs only the place."""
    return raw.split("(")[0].strip(" ,")


def queries(city: str, wide: bool) -> list[str]:
    b = _block(city)
    qs = list(b.get("queries", []))
    if wide:
        places = b.get("micro_markets", []) + b.get("noida_greater_noida", [])
        qs += [f'"{_name(m["n"])}" lease OR campus OR opens OR cafeteria' for m in places if isinstance(m, dict) and m.get("n")]
        qs += [f'"{_name(e["co"])}" {_name(e.get("ev", ""))} {city}'.strip() for e in b.get("recent_events_seen", []) if e.get("co")]
        qs += [f'"{i}" new campus OR building OR canteen OR tender' for i in b.get("institutions_seed", [])]
        qs += [f"site:{m.group(0)} {city} campus OR cafeteria OR lease" for s in b.get("local_media", []) if (m := SITE.search(s))]
    return list(dict.fromkeys(qs))


def pages(city: str, limit: int) -> list[str]:
    """URLs worth reading with Firecrawl: shared + this city's sources marked `a: fetch`, best priority first, seen-live first."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "u" in node:
                if node.get("a") == "fetch":
                    found.append(node)
            else:
                [walk(v) for v in node.values()]
        elif isinstance(node, list):
            [walk(v) for v in node]
    walk(cfg.yml("city_sources").get("shared", {}))
    walk(_block(city))
    found.sort(key=lambda s: (PRIORITY.get(s.get("p"), 3), -(s.get("v") or 0)))
    urls = [s["u"] if s["u"].startswith("http") else f"https://{s['u']}" for s in found]
    return list(dict.fromkeys(urls))[:limit]


def fetch_pages(city: str, limit: int = 6) -> list[Doc]:
    docs = []
    for url in pages(city, limit):
        try:
            d = web.scrape(url)
        except Exception as e:  # one dead or blocked page must not stop the rest
            print(f"city page skipped {url}: {type(e).__name__}")
            continue
        if d["markdown"]:
            docs.append(Doc(url=url, title=url, text=d["markdown"][:web.MAX_CHARS], date=date.today(), source="city_page"))
    return docs
