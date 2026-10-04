from src.models import Source
from src.sources import city_report, collect_city


def test_city_file_parses_with_every_kind_of_entry():
    rows = collect_city()
    groups = {r.group.split(".")[0] for r in rows}
    assert groups == {"shared", "bengaluru", "pune", "mumbai", "gurugram"}
    assert any(r.group == "shared.reits.embassy" and r.name == "embassy" for r in rows)                  # REITs are named by their key
    assert any(r.access == "media" and r.url == "https://thehindu.com" for r in rows)                    # "thehindu.com (Bengaluru)" -> domain
    assert not any("gurugramtoday" in r.url for r in rows)                                               # prose with no domain is skipped
    assert all(r.url.startswith("http") for r in rows)


def test_report_groups_by_city_then_category_and_lists_fixes():
    mk = lambda name, group, status, p="m", note="": Source(name=name, url="https://x.in/" + name, group=group, priority=p, status=status, note=note)
    rows = [mk("a", "pune.govt_bodies", "dead", "h"), mk("b", "pune.govt_bodies", "ok", "h"), mk("c", "mumbai.local_media", "ok"),
            mk("d", "shared.gcc_trackers", "unreachable"), mk("e", "pune.local_media", "ok", note="[redirects to new.in]")]
    t = city_report(rows, "2026-10-04")
    assert t.index("## All cities") < t.index("## Pune") < t.index("## Mumbai")                         # fixed city order
    pune = t[t.index("## Pune"):t.index("## Mumbai")]
    assert pune.index("| ok | h | b") < pune.index("| dead")                                           # priority first, then ok before dead
    assert "### Government, tenders and regulators" in pune and "### Local media" in pune
    fix = t[t.index("## Fix list"):]
    assert "find the current site" in fix and "open it in a browser" in fix and "| Pune | a" in fix
    assert "e: https://x.in/e -> new.in" in t                                                           # reachable but moved


def test_city_sources_feed_discovery():
    from src.discover import city, news
    base, wide = city.queries("Pune", False), city.queries("Pune", True)
    assert base and set(base) <= set(wide) and len(wide) > len(base) + 15           # micro-markets, seed leads, institutions, media
    assert any(q.startswith('"Hinjewadi') or "Hinjewadi" in q for q in wide) and any(q.startswith("site:") for q in wide)
    assert city.queries("Hyderabad", True) == []                                      # no block for that city: nothing invented
    assert set(wide) <= set(news.queries("Pune", True))                               # and they reach the news fetcher
    urls = city.pages("Hyderabad", 6)                                                 # shared fetchable sources work for every city
    assert urls and all(u.startswith("http") for u in urls) and urls[0].startswith("https://gccindex.in")
    assert city.pages("Pune", 99).count("https://mahatenders.gov.in/nicgep/app") == 1  # a city's own `a: fetch` source is added once


def test_one_failing_news_query_does_not_lose_the_rest(monkeypatch):
    from src.discover import news
    from src.models import Doc
    from datetime import date
    monkeypatch.setattr(news, "queries", lambda c, w: ["bad", "good"])
    monkeypatch.setattr(news, "_get", lambda q: (_ for _ in ()).throw(RuntimeError("404")) if q == "bad" else "x")
    monkeypatch.setattr(news, "parse", lambda xml: [Doc(url="u", title="t", text="t", date=date.today(), source="news")])
    assert len(news.fetch("Pune")) == 1
