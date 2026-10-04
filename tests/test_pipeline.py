from datetime import date

import pytest

from src import cfg, run, store
from src.discover import news
from src.extract import evidence_ok
from src.models import Account, Person, Signal
from src.resolve import canon, resolve
from src.score import contrib, score_all

TODAY = date(2026, 4, 1)


def sig(type_="new_campus", d=date(2026, 4, 1), account="a"):
    return Signal(id="s", account_id=account, type=type_, date=d, summary="x", source_url="u", evidence="e")


def test_evidence_substring_check():
    text = "Zentra will open a new\n  2,000-seat campus in Pune."
    assert evidence_ok("open a new 2,000-seat campus", text)  # whitespace-normalised
    assert not evidence_ok("open a 5,000-seat campus", text)
    assert not evidence_ok("", text)


def test_decay_halves_at_half_life():
    assert contrib(sig(d=date(2026, 4, 1)), TODAY) == 25
    assert contrib(sig(d=date(2026, 1, 1)), TODAY) == pytest.approx(25 * 0.5 ** (90 / 90))  # 90 days old
    assert contrib(sig("tender", date(2026, 1, 31)), TODAY) == pytest.approx(15)  # 60-day half life, weight 30


def test_resolve_dedupes():
    accs = []
    a = resolve(accs, "Zentra Systems Pvt Ltd", "Pune", "corporate")
    b = resolve(accs, "Zentra Systems", "Pune", "corporate", size_est=2000)
    assert a is b and len(accs) == 1 and a.size_est == 2000
    assert canon("Acme Pvt. Ltd.") == "acme"


def test_ranking_and_reason():
    accs = [Account(id=i, name=i, city="Pune", segment="corporate", first_seen=TODAY, size_est=n)
            for i, n in [("big", 2000), ("old", 2000)]]
    sigs = [sig(account="big"), sig(d=date(2025, 1, 1), account="old")]
    out = score_all(accs, sigs, [], TODAY)
    assert [s.account_id for s in out] == ["big", "old"] and out[0].rank == 1
    assert out[0].reason == "new campus (Apr 2026) + ~2,000 seats"


def test_reach_needs_verified_email():
    a = Account(id="a", name="a", city="Pune", segment="corporate", first_seen=TODAY)
    p = Person(account_id="a", role="r", name="N", email="n@a.com", email_status="valid", source="hunter", role_match=0.9)  # a target; a gatekeeper would give less
    assert score_all([a], [sig()], [p], TODAY)[0].reach == 12


def test_news_parse():
    xml = """<rss><channel><item><title>Acme opens campus</title><link>http://x/1</link>
    <pubDate>Tue, 10 Mar 2026 10:00:00 GMT</pubDate><description>&lt;a&gt;Acme opens campus&lt;/a&gt; in Pune</description></item></channel></rss>"""
    d = news.parse(xml)[0]
    assert d.date == date(2026, 3, 10) and "in Pune" in d.text and "<a>" not in d.text


def test_end_to_end_dry_run(monkeypatch, tmp_path_factory=None):
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as t:
        monkeypatch.setattr(store, "DIR", Path(t))
        monkeypatch.setattr(cfg, "dry", False)
        run.stats.clear()
        run.main(["all", "--city", "Pune", "--dry-run"])
        accs = {a.id for a in store.load("accounts", Account)}
        assert accs == {"zentra systems".replace(" ", "-"), "pune-institute-of-applied-sciences", "northwind-gcc"}
        assert run.stats["rejected_evidence"] == 1  # the fabricated Northwind campus
        assert len(store.load("signals", Signal)) == 3
        drafts = store.load("drafts", __import__("src.models", fromlist=["Draft"]).Draft)
        assert drafts and all(d.trigger_used in {s.id for s in store.load("signals", Signal)} for d in drafts)


def test_prefilter_keeps_signals_drops_noise():
    from src.extract import prefilter
    from src.models import Doc
    mk = lambda t: Doc(url="u", title=t, text=t, date=TODAY, source="news")
    assert prefilter(mk("Acme opens new campus in Bengaluru"))
    assert prefilter(mk("TVS Motor leases 5.29 lakh sq ft office"))
    assert not prefilter(mk("Bengaluru building collapses, three trapped"))
    assert not prefilter(mk("Acme Q1 profit rises 12%; share price up"))
    assert not prefilter(mk("Weekend weather in the city"))


def test_trigger_score_counts_one_signal_per_type():
    a = Account(id="a", name="a", city="Pune", segment="corporate", first_seen=TODAY)
    one = score_all([a], [sig()], [], TODAY)[0].trigger
    five = score_all([a], [sig() for _ in range(5)], [], TODAY)[0].trigger   # same event, five outlets
    assert one == five == 25
    assert score_all([a], [sig(), sig("lease")], [], TODAY)[0].trigger == 43  # different triggers still add
