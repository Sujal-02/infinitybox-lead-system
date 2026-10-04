"""Free discovery source: Google News RSS searches per city, turned into docs for extraction."""
import html
import re
import time
from datetime import date, datetime
from urllib.parse import quote

import feedparser
import requests

from ..cache import cached, retry
from ..cfg import yml
from ..models import Doc
from . import city as city_sources

RSS = "https://news.google.com/rss/search?q={q}+when:90d&hl=en-IN&gl=IN&ceid=IN:en"


def _get(q: str) -> str:
    def go():
        time.sleep(0.6)  # Google throttles bursts (it answers 404/429); only uncached requests wait
        r = requests.get(RSS.format(q=quote(q)), timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.text
    return cached("news", q, lambda: retry(go))


def parse(xml: str) -> list[Doc]:
    docs = []
    for e in feedparser.parse(xml).entries:
        body = html.unescape(re.sub(r"<[^>]+>", " ", e.get("summary", "")))
        d = datetime(*e.published_parsed[:6]).date() if e.get("published_parsed") else date.today()
        docs.append(Doc(url=e.link, title=e.title, text=f"{e.title}. {' '.join(body.split())}", date=d, source="news"))
    return docs


def queries(city: str, wide: bool) -> list[str]:
    qs = [q.format(city=city) for q in yml("cities")[city]["queries"]]
    qs += city_sources.queries(city, wide)  # micro-markets, seed leads, institutions, local media (config/city_sources.yaml)
    if wide:  # config/sources.yaml query bank: cafeteria, caterer, ESG, hiring, institution signals (free RSS)
        label = "Gurugram Noida" if city == "NCR" else city
        qs += [q.format(city=label) for group in yml("sources")["news"]["query_bank"].values() for q in group[:3]]
    return list(dict.fromkeys(qs))


def fetch(city: str, wide: bool = False) -> list[Doc]:
    docs, seen = [], set()
    for q in queries(city, wide):
        try:
            found = parse(_get(q))
        except Exception as e:  # one throttled or odd query must not lose the other 70
            print(f"news query skipped ({type(e).__name__}): {q[:60]}")
            continue
        for d in found:
            if d.title not in seen:
                seen.add(d.title)
                docs.append(d)
    return docs
