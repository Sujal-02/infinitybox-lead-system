import shutil
from datetime import date

import pytest

from src import cache, cfg, sheet
from src.models import Account


class FakeWS:
    def __init__(self, title):
        self.title, self.rows = title, []

    def row_values(self, n):
        return self.rows[0] if self.rows else []

    def append_row(self, r):
        self.rows.append(r)

    def append_rows(self, rs):
        self.rows.extend(rs)

    def get_all_records(self):
        h = self.rows[0]
        return [dict(zip(h, r)) for r in self.rows[1:]]

    def clear(self):
        self.rows = []


class FakeBook:
    def __init__(self):
        self.ws = {}

    def worksheets(self):
        return list(self.ws.values())

    def worksheet(self, t):
        return self.ws[t]

    def add_worksheet(self, title, rows, cols):
        self.ws[title] = FakeWS(title)


def test_init_creates_all_tabs_once():
    b = FakeBook()
    assert set(sheet.init(b)) == set(sheet.TABS) | {"Events"}
    assert sheet.init(b) == []  # idempotent
    assert b.ws["Scores"].rows[0] == ["account_id", "fit", "trigger", "reach", "total", "reason", "rank", "updated", "city"]


def test_append_and_read_roundtrip():
    b = FakeBook()
    sheet.init(b)
    a = Account(id="a1", name="Acme", city="Pune", segment="corporate", first_seen=date(2026, 3, 1))
    sheet.append(b, "Accounts", [a])
    assert sheet.read(b, "Accounts") == [a]


def test_cache_hits_disk(monkeypatch):
    monkeypatch.setattr(cache, "DIR", cfg.ROOT / "cache" / "_test")
    calls = []
    f = lambda: calls.append(1) or {"x": 1}
    assert cache.cached("t", {"q": 1}, f) == cache.cached("t", {"q": 1}, f) == {"x": 1}
    assert len(calls) == 1
    cache.cached("t", {"q": 2}, f)
    assert len(calls) == 2
    shutil.rmtree(cache.DIR)


def test_unlisted_actor_refused():
    with pytest.raises(PermissionError):
        cfg.actor("linkedin_with_cookies")


def test_script_gateway_behaves_like_a_sheet(monkeypatch):
    """The Apps Script gateway (no Google Cloud key) must work with the same init/append/read/replace calls."""
    import json
    store = {}

    class Resp:
        def __init__(self, j): self.j, self.status_code = j, 200
        def json(self): return self.j

    def post(url, data, headers, timeout):
        d = json.loads(data)
        assert d["token"] == "t"
        op, t = d["op"], d.get("title")
        if op == "list": return Resp({"ok": True, "title": "Book", "titles": list(store)})
        if op == "add": store.setdefault(t, []); return Resp({"ok": True})
        if op == "values": return Resp({"ok": True, "values": store[t]})
        if op == "append": store[t].extend(d["rows"]); return Resp({"ok": True})
        if op == "clear": store[t] = []; return Resp({"ok": True})
    import requests
    monkeypatch.setattr(requests, "post", post)
    b = sheet.ScriptBook("http://x", "t")
    assert set(sheet.init(b)) == set(sheet.TABS) | {"Events"} and sheet.init(b) == []
    a = Account(id="a1", name="Acme", city="Pune", segment="corporate", first_seen=date(2026, 3, 1))
    sheet.append(b, "Accounts", [a])
    assert sheet.read(b, "Accounts")[0].name == "Acme"
    sheet.replace(b, "Accounts", [])
    assert store["Accounts"] == [sheet.columns("Accounts")]


def test_sheet_outage_never_stops_the_pipeline(monkeypatch):
    from src import run
    monkeypatch.setattr(run.cfg, "dry", False)
    monkeypatch.setattr(run, "_push_to_sheet", lambda: (_ for _ in ()).throw(RuntimeError("gateway down")))
    monkeypatch.setattr(run, "export_workbook", lambda path=None: "wb.xlsx")
    run.sync()  # must not raise


def test_gateway_retries_an_empty_reply(monkeypatch):
    import requests
    calls = []

    class R:
        def __init__(self, ok): self.ok = ok
        def json(self):
            if not self.ok: raise ValueError("empty")
            return {"ok": True, "titles": ["A"]}
    monkeypatch.setattr(requests, "post", lambda *a, **k: calls.append(1) or R(len(calls) > 1))
    monkeypatch.setattr(sheet.time, "sleep", lambda s: None)
    assert [w.title for w in sheet.ScriptBook("http://x", "t").worksheets()] == ["A"] and len(calls) == 2


def test_setup_script_keeps_other_settings_and_never_prints_keys(tmp_path_factory=None):
    import setup_local as s
    from src import cfg
    d = cfg.ROOT / "cache" / "_setup_test"
    d.mkdir(parents=True, exist_ok=True)
    env = d / ".env"
    env.write_text("# my notes\nGEMINI_API_KEY=\nCITY=Pune\n", "utf-8")
    s.write_env({"GEMINI_API_KEY": "key-1234567890", "HUNTER_API_KEY": "h-abcdefghij", "DRY_RUN": "0"}, env)
    got = s.read_env(env)
    assert got["GEMINI_API_KEY"] == "key-1234567890" and got["CITY"] == "Pune" and got["DRY_RUN"] == "0"
    assert env.read_text("utf-8").startswith("# my notes")
    assert s.mask("key-1234567890") == "...7890" and "key-12" not in s.mask("key-1234567890") and s.mask("") == "(not set)"
    assert all(x["does"] and x["without"] and x["free"] for x in s.SERVICES) and [x["required"] for x in s.SERVICES].count(True) == 1


def _city_tables(city, name, *, status="new"):
    from src.models import Draft, LeadRow, Person, Score, Signal
    a = Account(id=name.lower(), name=name, city=city, segment="corporate", first_seen=date(2026, 3, 1), status=status)
    return {"Accounts": [a],
            "Signals": [Signal(id="s1", account_id=a.id, type="new_campus", date=date(2026, 3, 1), summary="s", source_url="u", evidence="e")],
            "People": [Person(account_id=a.id, role="Head of Facilities", name="N", source="website")],
            "Scores": [Score(account_id=a.id, fit=1, trigger=2, reach=3, total=6, reason="r", rank=1)],
            "Drafts": [Draft(account_id=a.id, role="r", subject="s", body="b", trigger_used="s1")],
            "Pipeline": [LeadRow(rank=1, account=name, city=city, segment="corporate", total=6, fit=1, trigger=2, reach=3, reason="r", triggers="new_campus", newest_signal="2026-03-01")]}


def test_sheet_is_a_database_keyed_by_city():
    """A run for one city must not erase another's rows; export then import returns the same data; sheet edits to status survive."""
    b = FakeBook()
    sheet.push(b, _city_tables("Pune", "Acme"))
    sheet.push(b, _city_tables("Bangalore", "Beta"))
    assert sheet.cities(b) == {"Pune": 1, "Bangalore": 1}                       # the second city did not wipe the first
    b.ws["Accounts"].rows[1][b.ws["Accounts"].rows[0].index("status")] = "contacted"   # someone edits the sheet by hand
    sheet.push(b, _city_tables("Pune", "Acme"))                                   # re-running Pune replaces its rows only
    got = sheet.pull(b, "Pune")
    assert [a.name for a in got["Accounts"]] == ["Acme"] and got["Accounts"][0].status == "contacted"
    assert len(got["Signals"]) == len(got["People"]) == len(got["Scores"]) == len(got["Drafts"]) == 1
    assert sheet.pull(b, "Bangalore")["Accounts"][0].name == "Beta" and sheet.pull(b, "Mumbai")["Accounts"] == []
    assert len(b.ws["Pipeline"].rows) == 3                                        # header + one row per city


def test_same_company_in_two_cities_does_not_collide_in_the_sheet():
    """TCS can be a lead in Pune and in Bangalore with the same account id: saving one city must keep the other's row."""
    b = FakeBook()
    sheet.push(b, _city_tables("Pune", "Tcs"))
    sheet.push(b, _city_tables("Bangalore", "Tcs"))
    assert sheet.cities(b) == {"Pune": 1, "Bangalore": 1}
    sheet.push(b, _city_tables("Bangalore", "Tcs"))                               # re-saving Bangalore again
    for city in ("Pune", "Bangalore"):
        got = sheet.pull(b, city)
        assert len(got["Accounts"]) == len(got["Signals"]) == len(got["People"]) == len(got["Scores"]) == len(got["Drafts"]) == 1
        assert got["Signals"][0].city == city

