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
    assert set(sheet.init(b)) == set(sheet.TABS)
    assert sheet.init(b) == []  # idempotent
    assert b.ws["Scores"].rows[0] == ["account_id", "fit", "trigger", "reach", "total", "reason", "rank", "updated"]


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
