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
